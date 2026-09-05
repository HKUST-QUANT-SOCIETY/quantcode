"""Risk CI GitHub comment E2E tests (mocked API).

Covers scripted ``runner.risk_ci`` flows with formal PR comment posting:
normal/high-risk reports and GitHub marker dedupe. Risk verdicts never gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runner.compose_executor import execute_compose_flow, unregister_flow
from runner.langgraph_base import clear_checkpointer_cache, make_thread_id
from runner.risk_ci import build_risk_ci_flow, register_risk_ci_flow
from tools.risk.risk_tools import clear_write_pr_comment_dedupe_cache


def _fixture_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _flow_input(tmp_path: Path, **overrides) -> dict[str, Any]:
    data: dict[str, Any] = {
        "scenario": "normal",
        "model_spec": _fixture_model_spec(),
        "pr_number": "42",
        "head_sha": "abcdef1234567890",
        "pr_url": "https://github.com/example/repo/pull/42",
        "dedupe_db_path": str(tmp_path / "dedupe.sqlite"),
        "artifacts_root": str(tmp_path / "pr-comments"),
        "post_to_github": True,
        "github_repo": "example/repo",
        "github_token": "test-token",
    }
    data.update(overrides)
    return data


class FakeGitHubStore:
    """In-memory GitHub comments API for deterministic E2E tests."""

    def __init__(self) -> None:
        self.comments: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self._next_id = 1000

    def github_request(
        self,
        method: str,
        repo: str,
        path: str,
        token: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append({
            "method": method,
            "repo": repo,
            "path": path,
            "token": token,
            "payload": payload,
        })
        if method == "GET" and path.startswith("/issues/") and path.endswith("/comments"):
            return list(self.comments)
        if method == "POST" and path.endswith("/comments"):
            comment = {
                "id": self._next_id,
                "html_url": (
                    f"https://github.com/{repo}/pull/"
                    f"{path.split('/')[2]}#issuecomment-{self._next_id}"
                ),
                "body": (payload or {}).get("body", ""),
            }
            self._next_id += 1
            self.comments.append(comment)
            return comment
        raise AssertionError(f"Unexpected GitHub API call: {method} {path}")

    def find_existing_comment(
        self,
        repo: str,
        pr_number: str,
        token: str,
        marker: str,
    ) -> dict[str, Any] | None:
        for comment in self.comments:
            if marker in str(comment.get("body", "")):
                return comment
        return None

    def post_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == "POST"]


@pytest.fixture
def fake_github(monkeypatch) -> FakeGitHubStore:
    store = FakeGitHubStore()
    monkeypatch.setattr("tools.risk.risk_tools.github_request", store.github_request)
    monkeypatch.setattr(
        "tools.risk.risk_tools.find_existing_comment",
        store.find_existing_comment,
    )
    return store


@pytest.fixture(autouse=True)
def cleanup():
    yield
    clear_checkpointer_cache()
    clear_write_pr_comment_dedupe_cache()
    unregister_flow("risk", "risk:ci")


def test_normal_flow_posts_github_comment(tmp_path, monkeypatch, fake_github):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    monkeypatch.chdir(tmp_path)
    thread_id = make_thread_id("risk", "risk:ci", ts=20, suffix="gh-normal")
    register_risk_ci_flow(checkpoint_db=tmp_path / "checkpoints.db")

    result = execute_compose_flow(
        group="risk",
        flow_name="risk:ci",
        input_data=_flow_input(tmp_path),
        thread_id=thread_id,
    )

    output = result["output_data"]
    assert output["status"] == "completed"
    pr_comment = output["pr_comment"]
    assert pr_comment is not None
    assert pr_comment["github_comment_id"] == "1000"
    assert "issuecomment-1000" in pr_comment["github_comment_url"]
    assert len(fake_github.post_calls()) == 1
    body = fake_github.post_calls()[0]["payload"]["body"]
    assert "QuantCode Risk CI Report" in body
    assert "<!-- quantcode:risk-ci:profile:abcdef1234567890:" in body


def test_normal_flow_github_marker_dedupes_repeat_run(tmp_path, monkeypatch, fake_github):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    monkeypatch.chdir(tmp_path)
    register_risk_ci_flow(checkpoint_db=tmp_path / "checkpoints.db")
    flow_input = _flow_input(tmp_path)

    for suffix in ("gh-dedupe-1", "gh-dedupe-2"):
        thread_id = make_thread_id("risk", "risk:ci", ts=21, suffix=suffix)
        result = execute_compose_flow(
            group="risk",
            flow_name="risk:ci",
            input_data=flow_input,
            thread_id=thread_id,
        )
        assert result["output_data"]["status"] == "completed"

    assert len(fake_github.comments) == 1
    assert len(fake_github.post_calls()) == 1


def test_high_risk_writes_failed_ci_report_without_gate(tmp_path, monkeypatch, fake_github):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    monkeypatch.chdir(tmp_path)
    app = build_risk_ci_flow(checkpoint_db=tmp_path / "checkpoints.db")
    thread_id = make_thread_id("risk", "risk:ci", ts=22, suffix="gh-payload")
    config = {"configurable": {"thread_id": thread_id}}

    result = app.invoke(
        {
            "group": "risk",
            "flow_name": "risk:ci",
            "thread_id": thread_id,
            "input_data": _flow_input(tmp_path, scenario="high_risk"),
            "output_data": None,
            "artifacts": [],
            "errors": [],
        },
        config=config,
    )

    output = result["output_data"]
    assert output["status"] == "completed_with_warning"
    assert output["risk_verdict"]["breached"] is True
    assert output["pr_comment"]["github_comment_id"] == "1000"
    assert len(fake_github.post_calls()) == 1
    assert "__interrupt__" not in result
