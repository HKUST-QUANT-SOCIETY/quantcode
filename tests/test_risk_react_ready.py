"""Risk ReAct-readiness smoke tests.

These tests do not claim that risk already has a complete HumanGate ReAct path.
They prove the part owned by risk is ready: the allowlisted tools can be called
in a ReAct-style sequence and the sequence reaches a stable gate result. The
missing piece is the shared AgentRunner route_gate / interrupt-resume branch.
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


class ScriptedRiskLLM:
    """Mock LLM that walks the risk allowlist in the intended ReAct order."""

    def __init__(self, model_spec: dict, *, scenario: str):
        self.model_spec = model_spec
        self.scenario = scenario
        self.calls: list[list[str]] = []
        self._idx = 0
        self._risk_metrics = {
            "strategy_id": model_spec["model_name"],
            "as_of_date": "2026-07-06",
            "max_drawdown": 0.22 if scenario == "high_risk" else 0.08,
            "position_limit": 0.45,
            "correlation_with_existing": 0.3,
            "capacity_estimate_usd": 50_000_000.0,
            "tail_risk_var_99": 0.08 if scenario == "high_risk" else 0.025,
        }
        self._risk_profile = dict(self._risk_metrics)

    def __call__(self, messages, tools=None):
        self.calls.append(sorted(t.id for t in (tools or [])))
        responses = [
            _ai_with_tools(
                [
                    (
                        "read_blackboard",
                        {"input_data": {"model_spec": self.model_spec}},
                    ),
                    (
                        "calc_risk",
                        {
                            "model_spec": self.model_spec,
                            "scenario": self.scenario,
                        },
                    ),
                    (
                        "generate_risk_profile",
                        {
                            "model_spec": self.model_spec,
                            "risk_metrics": self._risk_metrics,
                            "pr_url": "https://github.com/example/repo/pull/42",
                        },
                    ),
                    (
                        "check_gate",
                        {"risk_profile": self._risk_profile},
                    ),
                ],
                "risk",
            ),
            AIMessage(content="Reached HumanGate boundary."),
        ]
        response = responses[self._idx] if self._idx < len(responses) else responses[-1]
        self._idx += 1
        return response


def _ai_with_tools(name_to_args: list[tuple[str, dict]], call_id_prefix: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"{call_id_prefix}-{i}"}
            for i, (name, args) in enumerate(name_to_args)
        ],
    )


def _sample_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def reload_risk_tools():
    importlib.reload(tools.risk._register)
    yield
    clear_checkpointer_cache()


def test_risk_tools_are_react_ready_until_human_gate_boundary(tmp_path):
    model_spec = _sample_model_spec()
    llm = ScriptedRiskLLM(model_spec, scenario="high_risk")
    runner = AgentRunner(group="risk", model=llm, checkpoint_db=tmp_path / "checkpoint.db")

    final = runner.run(
        task="Run risk gate for PR #42 with a high-risk profile",
        skill_name="risk-gate",
        thread_id="risk-react-ready-high-risk",
    )

    allowed = set(llm.calls[0])
    assert {"read_blackboard", "calc_risk", "generate_risk_profile", "check_gate"} <= allowed
    assert "write_pr_comment" in allowed
    assert "read_pr" not in allowed

    tool_outputs = [str(getattr(m, "content", "")) for m in final["messages"]]
    assert any("requires_human" in output and "True" in output for output in tool_outputs)
    assert any("max_drawdown" in output for output in tool_outputs)
    assert any("tail_risk_var_99" in output for output in tool_outputs)
    # Day 5（甲方案）：确定性引擎在 check_gate(requires_human=True) 后路由到
    # _human_gate_node 并 interrupt()，不再回 LLM 生成 "Reached HumanGate boundary." 文本。
    # HumanGate 边界体现为 __interrupt__ 存在 + check_gate 输出停在最后一条。
    assert "__interrupt__" in final, "high-risk 应在 HumanGate 处 interrupt"
    last_content = str(getattr(final["messages"][-1], "content", ""))
    assert "requires_human" in last_content and "True" in last_content
