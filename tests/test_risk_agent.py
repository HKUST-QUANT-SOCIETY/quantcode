"""Smoke test — risk agent scripted pipeline + tool registry."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

import tools.risk._register  # noqa: F401
from runner.compose_executor import execute_compose_flow, unregister_flow
from runner.langgraph_base import clear_checkpointer_cache, make_thread_id
from runner.risk_agent import register_risk_gate_flow
from tools.registry import registry
from tools.risk.risk_tools import clear_write_pr_comment_dedupe_cache


def _fixture_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def cleanup():
    import tools.model._register  # noqa: F401
    importlib.reload(tools.risk._register)
    yield
    clear_checkpointer_cache()
    clear_write_pr_comment_dedupe_cache()
    unregister_flow("risk", "risk:gate")


def test_risk_allowlist_matches_registered_tools():
    tools = registry.get_tools_for_group("risk")
    assert {t.id for t in tools} == {
        "read_blackboard",
        "calc_risk",
        "calc_risk_stub",
        "generate_risk_profile",
        "check_gate",
        "write_pr_comment",
        "request_human_review",
        "spawn_risk_scout",
    }


def test_risk_agent_normal_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    monkeypatch.chdir(tmp_path)
    thread_id = make_thread_id("risk", "risk:gate", ts=10, suffix="agent-normal")
    register_risk_gate_flow(checkpoint_db=tmp_path / "checkpoints.db")

    result = execute_compose_flow(
        group="risk",
        flow_name="risk:gate",
        input_data={
            "scenario": "normal",
            "model_spec": _fixture_model_spec(),
            "pr_number": "42",
            "head_sha": "abcdef1234567890",
            "pr_url": "https://github.com/hkust-quant-society/quantcode/pull/42",
            "dedupe_db_path": str(tmp_path / "dedupe.sqlite"),
            "artifacts_root": str(tmp_path / "pr-comments"),
        },
        thread_id=thread_id,
    )

    assert result["output_data"]["status"] == "completed"
    assert result["output_data"]["pr_comment"] is not None
