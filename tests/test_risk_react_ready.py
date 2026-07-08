"""Risk ReAct-readiness smoke — delegates to AgentRunner gate integration.

Full interrupt/resume coverage lives in ``tests/test_risk_agent_runner.py``.
This module keeps a lightweight import/smoke so older CI references still pass.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import tools.risk._register  # noqa: F401
from runner.agent_engine import AgentRunner
from runner.langgraph_base import clear_checkpointer_cache
from tools.registry import registry


@pytest.fixture(autouse=True)
def reload_risk_tools():
    importlib.reload(tools.risk._register)
    yield
    clear_checkpointer_cache()


def test_risk_allowlist_exposes_gate_tools(tmp_path):
    """Risk MCP/AgentRunner allowlist includes check_gate + write_pr_comment."""
    tool_ids = {t.id for t in registry.get_tools_for_group("risk")}
    assert {"read_blackboard", "calc_risk", "generate_risk_profile", "check_gate", "write_pr_comment"} <= tool_ids


def test_risk_agent_runner_gate_tools_require_checkpoint(tmp_path):
    """gate_tools path requires checkpoint_db (yifan-day4 contract)."""
    llm = lambda messages, tools=None: AIMessage(content="done")
    with pytest.raises(ValueError, match="checkpoint_db"):
        AgentRunner(group="risk", model=llm, gate_tools=["check_gate"])


def test_risk_agent_runner_smoke_with_gate(tmp_path):
    """Minimal AgentRunner(group=risk) run with gate_tools compiles and returns."""
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    model_spec = json.loads(path.read_text(encoding="utf-8"))
    llm = lambda messages, tools=None: AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_blackboard",
                "args": {"input_data": {"model_spec": model_spec}},
                "id": "smoke-0",
            }
        ],
    )
    runner = AgentRunner(
        group="risk",
        model=llm,
        gate_tools=["check_gate"],
        checkpoint_db=tmp_path / "cp.db",
    )
    final = runner.run(task="smoke", skill_name="risk-gate", thread_id="risk-smoke-1")
    assert final.get("iterations", 0) >= 1
