"""Risk group AgentRunner integration — Day 4 杨欣琳.

Exercises ``AgentRunner(group="risk", gate_tools=["check_gate"])`` with the full
tool chain: read_blackboard → calc_risk → generate_risk_profile → check_gate →
HumanGate interrupt/resume → write_pr_comment (or skip on reject).
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import tools.risk._register  # noqa: F401
from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache
from tools.risk.risk_tools import (
    calc_risk,
    clear_write_pr_comment_dedupe_cache,
    generate_risk_profile,
)


def _sample_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _ai_with_tools(calls: list[tuple[str, dict]], prefix: str = "risk") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"{prefix}-{i}"}
            for i, (name, args) in enumerate(calls)
        ],
    )


def _risk_profile_dict(model_spec: dict, scenario: str) -> dict:
    metrics = calc_risk(model_spec, scenario=scenario)
    profile = generate_risk_profile(
        model_spec,
        metrics,
        pr_url="https://github.com/example/repo/pull/42",
    )
    return profile.model_dump(mode="json")


def _write_pr_comment_args(profile: dict, tmp_path: Path | None = None) -> dict:
    root = str(tmp_path / "pr-comments") if tmp_path else "artifacts/risk/pr-comments"
    return {
        "risk_profile": profile,
        "pr_number": "42",
        "head_sha": "abcdef1234567890",
        "pr_url": "https://github.com/example/repo/pull/42",
        "artifacts_root": root,
        "dedupe_db_path": str(tmp_path / "dedupe.sqlite") if tmp_path else None,
    }


class ScriptedRiskLLM:
    """Step-through LLM for deterministic risk AgentRunner tests."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="[risk agent done]")
        self._idx += 1
        return resp


@pytest.fixture(autouse=True)
def _reload_risk_tools():
    importlib.reload(tools.risk._register)
    yield
    clear_checkpointer_cache()
    clear_write_pr_comment_dedupe_cache()


def _risk_runner(llm: ScriptedRiskLLM, tmp_path: Path) -> AgentRunner:
    return AgentRunner(
        group="risk",
        model=llm,
        gate_tools=["check_gate"],
        checkpoint_db=tmp_path / "checkpoint.db",
        max_iterations=12,
    )


def _tool_messages(state: dict) -> list[ToolMessage]:
    return [m for m in state.get("messages", []) if isinstance(m, ToolMessage)]


def test_risk_agent_runner_normal_no_interrupt_writes_comment(tmp_path):
    model_spec = _sample_model_spec()
    profile = _risk_profile_dict(model_spec, "normal")
    metrics = calc_risk(model_spec, "normal")
    llm = ScriptedRiskLLM(
        [
            _ai_with_tools(
                [
                    ("read_blackboard", {"input_data": {"model_spec": model_spec}}),
                    ("calc_risk", {"model_spec": model_spec, "scenario": "normal"}),
                    (
                        "generate_risk_profile",
                        {
                            "model_spec": model_spec,
                            "risk_metrics": metrics,
                            "pr_url": "https://github.com/example/repo/pull/42",
                        },
                    ),
                ]
            ),
            _ai_with_tools([("check_gate", {"risk_profile": profile})]),
            _ai_with_tools([("write_pr_comment", _write_pr_comment_args(profile, tmp_path))]),
            AIMessage(content="Risk gate completed."),
        ]
    )
    final = _risk_runner(llm, tmp_path).run(
        task="Run normal risk gate for PR #42",
        skill_name="risk-gate",
        thread_id="risk-ar-normal",
    )

    assert "__interrupt__" not in final or not final.get("__interrupt__")
    assert final.get("gate_decision") is None
    names = [m.name for m in _tool_messages(final)]
    assert "check_gate" in names
    assert "write_pr_comment" in names
    assert final["messages"][-1].content == "Risk gate completed."


def test_risk_agent_runner_high_risk_approve_interrupt_resume_writes_comment(tmp_path):
    model_spec = _sample_model_spec()
    profile = _risk_profile_dict(model_spec, "high_risk")
    metrics = calc_risk(model_spec, "high_risk")
    llm = ScriptedRiskLLM(
        [
            _ai_with_tools(
                [
                    ("read_blackboard", {"input_data": {"model_spec": model_spec}}),
                    ("calc_risk", {"model_spec": model_spec, "scenario": "high_risk"}),
                    (
                        "generate_risk_profile",
                        {
                            "model_spec": model_spec,
                            "risk_metrics": metrics,
                            "pr_url": "https://github.com/example/repo/pull/42",
                        },
                    ),
                ]
            ),
            _ai_with_tools([("check_gate", {"risk_profile": profile})]),
            _ai_with_tools([("write_pr_comment", _write_pr_comment_args(profile, tmp_path))]),
            AIMessage(content="Approved and commented."),
        ]
    )
    runner = _risk_runner(llm, tmp_path)
    paused = runner.run(
        task="Run high-risk gate for PR #42",
        skill_name="risk-gate",
        thread_id="risk-ar-approve",
    )

    assert paused.get("__interrupt__")
    payload = paused["__interrupt__"][0].value
    assert payload["message"] == "⏸️ 等待人工审批"
    assert payload.get("decision") is None
    assert payload["risk_profile"]["strategy_id"] == "pb_roe_ranker"
    assert "max_drawdown" in payload["reasons"]

    final = runner.resume("risk-ar-approve", "approve", skill_name="risk-gate")
    assert final.get("gate_decision") == "approve"
    assert final.get("human_gate_payload", {}).get("decision") == "approve"
    names = [m.name for m in _tool_messages(final)]
    assert "write_pr_comment" in names
    assert not final.get("__interrupt__")


def test_risk_agent_runner_high_risk_reject_skips_write_pr_comment(tmp_path):
    model_spec = _sample_model_spec()
    profile = _risk_profile_dict(model_spec, "high_risk")
    metrics = calc_risk(model_spec, "high_risk")
    llm = ScriptedRiskLLM(
        [
            _ai_with_tools(
                [
                    ("read_blackboard", {"input_data": {"model_spec": model_spec}}),
                    ("calc_risk", {"model_spec": model_spec, "scenario": "high_risk"}),
                    (
                        "generate_risk_profile",
                        {
                            "model_spec": model_spec,
                            "risk_metrics": metrics,
                            "pr_url": "https://github.com/example/repo/pull/42",
                        },
                    ),
                ]
            ),
            _ai_with_tools([("check_gate", {"risk_profile": profile})]),
            _ai_with_tools([("write_pr_comment", _write_pr_comment_args(profile, tmp_path))]),
            AIMessage(content="Rejected, no comment."),
        ]
    )
    runner = _risk_runner(llm, tmp_path)
    runner.run(
        task="Run high-risk gate for PR #42",
        skill_name="risk-gate",
        thread_id="risk-ar-reject",
    )
    final = runner.resume("risk-ar-reject", "reject", skill_name="risk-gate")

    assert final.get("gate_decision") == "reject"
    write_msgs = [m for m in _tool_messages(final) if m.name == "write_pr_comment"]
    if write_msgs:
        assert "skipped" in write_msgs[-1].content or "human_gate_rejected" in write_msgs[-1].content
    assert final["messages"][-1].content == "Rejected, no comment."


def test_risk_agent_runner_github_marker_dedupe_mock(tmp_path, monkeypatch):
    model_spec = _sample_model_spec()
    profile = _risk_profile_dict(model_spec, "normal")
    posts: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []

    def fake_github_request(method, repo, path, token, payload=None):
        if method == "GET":
            return list(comments)
        posts.append(payload or {})
        comment = {
            "id": 9001,
            "html_url": f"https://github.com/{repo}/pull/42#issuecomment-9001",
            "body": (payload or {}).get("body", ""),
        }
        comments.append(comment)
        return comment

    def fake_find_existing(repo, pr_number, token, marker):
        for c in comments:
            if marker in c.get("body", ""):
                return c
        return None

    monkeypatch.setattr("tools.risk.risk_tools.github_request", fake_github_request)
    monkeypatch.setattr("tools.risk.risk_tools.find_existing_comment", fake_find_existing)

    llm = ScriptedRiskLLM(
        [
            _ai_with_tools(
                [
                    ("read_blackboard", {"input_data": {"model_spec": model_spec}}),
                    ("calc_risk", {"model_spec": model_spec, "scenario": "normal"}),
                    (
                        "generate_risk_profile",
                        {
                            "model_spec": model_spec,
                            "risk_metrics": calc_risk(model_spec, "normal"),
                            "pr_url": "https://github.com/example/repo/pull/42",
                        },
                    ),
                ]
            ),
            _ai_with_tools([("check_gate", {"risk_profile": profile})]),
            _ai_with_tools(
                [
                    (
                        "write_pr_comment",
                        {
                            **_write_pr_comment_args(profile, tmp_path),
                            "post_to_github": True,
                            "github_repo": "example/repo",
                            "github_token": "test-token",
                        },
                    )
                ]
            ),
            AIMessage(content="done"),
        ]
    )
    runner = _risk_runner(llm, tmp_path)
    runner.run(
        task="post github comment",
        skill_name="risk-gate",
        thread_id="risk-ar-gh-1",
    )

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    llm2 = ScriptedRiskLLM(
        [
            _ai_with_tools(
                [
                    (
                        "write_pr_comment",
                        {
                            **_write_pr_comment_args(profile, tmp_path),
                            "post_to_github": True,
                            "github_repo": "example/repo",
                            "github_token": "test-token",
                        },
                    )
                ]
            ),
            AIMessage(content="done2"),
        ]
    )
    runner2 = AgentRunner(
        group="risk",
        model=llm2,
        gate_tools=["check_gate"],
        checkpoint_db=tmp_path / "checkpoint2.db",
        max_iterations=5,
    )
    runner2.run(
        task="post again",
        skill_name="risk-gate",
        thread_id="risk-ar-gh-2",
    )

    assert len(posts) == 1
    assert "QuantCode Risk Gate Report" in posts[0]["body"]
