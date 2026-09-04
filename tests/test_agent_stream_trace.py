"""test_agent_stream_trace.py — Day4 control-plane state backflow tests.

验证：
1. AgentRunner.stream() 使用真实 stream 路径，而不是调用 run() 再事后重建；
2. trace 至少包含 agent_start / tool_call / tool_result / agent_end；
3. HumanGate trace 会回流 waiting_for_human。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from runner.agent_engine import AgentRunner
from tools.registry import ToolDef, register_tool
from tools.registry import registry as global_registry


class ScriptedLLM:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="done")
        self._idx += 1
        return resp


def _ai_with_tools(name_to_args: list[tuple[str, dict]], call_id_prefix: str = "c"):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"{call_id_prefix}-{i}"}
            for i, (name, args) in enumerate(name_to_args)
        ],
    )


class EchoArgs(BaseModel):
    text: str


def _echo(args: EchoArgs, ctx: dict) -> dict[str, Any]:
    return {"echo": args.text}


ECHO = ToolDef(
    id="echo_tool",
    description="Return echo payload",
    schema=EchoArgs,
    execute=_echo,
)


class OutputArgs(BaseModel):
    ok: bool = True


def _produce_output(args: OutputArgs, ctx: dict) -> dict[str, Any]:
    return {
        "output_data": {"ok": args.ok},
        "artifacts": ["artifact-a.txt"],
        "task_status": "done",
    }


PRODUCE_OUTPUT = ToolDef(
    id="produce_output",
    description="Return output_data and artifacts",
    schema=OutputArgs,
    execute=_produce_output,
)


@pytest.fixture
def clean_registry():
    global_registry._tools.clear()
    yield
    global_registry._tools.clear()


@pytest.fixture
def tmp_db(tmp_path: Path):
    return tmp_path / "trace-checkpoints.sqlite"


def test_stream_does_not_call_run(monkeypatch, tmp_db, clean_registry):
    register_tool(ECHO)

    llm = ScriptedLLM([
        _ai_with_tools([("echo_tool", {"text": "hello"})]),
        AIMessage(content="done"),
    ])
    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db)

    def _fail_run(*args, **kwargs):
        raise AssertionError("stream() should not call run()")

    monkeypatch.setattr(runner, "run", _fail_run)

    result = runner.stream(
        task="trace test",
        system_prompt="x",
        thread_id="trace-stream-1",
        flow_name="trace_test",
    )
    assert "execution_trace" in result
    assert len(result["execution_trace"]) > 0


def test_stream_trace_contains_tool_call_and_result(tmp_db, clean_registry):
    register_tool(ECHO)

    llm = ScriptedLLM([
        _ai_with_tools([("echo_tool", {"text": "hello"})], "step1"),
        AIMessage(content="final answer"),
    ])
    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db)
    result = runner.stream(
        task="trace test",
        system_prompt="x",
        thread_id="trace-stream-2",
        flow_name="trace_test",
    )

    trace = result["execution_trace"]
    types = [e["type"] for e in trace]
    assert "agent_start" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "agent_end" in types

    tool_call = next(e for e in trace if e["type"] == "tool_call")
    tool_result = next(e for e in trace if e["type"] == "tool_result")
    assert tool_call["data"]["tool"] == "echo_tool"
    assert tool_result["data"]["tool"] == "echo_tool"


def test_stream_trace_includes_output_data_and_artifacts(tmp_db, clean_registry):
    register_tool(PRODUCE_OUTPUT)

    llm = ScriptedLLM([
        _ai_with_tools([("produce_output", {"ok": True})], "step1"),
        AIMessage(content="ignored because task done"),
    ])
    runner = AgentRunner(group="model", model=llm, checkpoint_db=tmp_db)
    result = runner.stream(
        task="produce output",
        system_prompt="x",
        thread_id="trace-stream-3",
        flow_name="trace_test",
    )

    assert result.get("output_data") == {"ok": True}
    assert result.get("artifacts") == ["artifact-a.txt"]

    trace = result["execution_trace"]
    assert any(e["type"] == "output_data" for e in trace)
    assert any(e["type"] == "artifact" for e in trace)


def test_stream_trace_risk_verdict_has_no_human_gate(tmp_db, clean_registry):
    from tools.risk._register import calc_risk_tool, generate_risk_profile_tool
    from tools.risk.statistics_stub import calc_risk_stub

    register_tool(calc_risk_tool)
    register_tool(generate_risk_profile_tool)

    risk_metrics = calc_risk_stub("high_risk")
    model_spec = {"model_name": "pb_roe_ranker"}

    llm = ScriptedLLM([
        _ai_with_tools(
            [
                ("calc_risk", {"model_spec": model_spec, "scenario": "high_risk"}),
                ("generate_risk_profile", {"model_spec": model_spec, "risk_metrics": risk_metrics}),
            ],
            "step1",
        ),
    ])
    runner = AgentRunner(group="risk", model=llm, checkpoint_db=tmp_db)
    result = runner.stream(
        task="check high risk",
        system_prompt="x",
        thread_id="trace-stream-4",
        flow_name="trace_test",
    )

    assert result.get("status") != "waiting_for_human"
    assert result.get("gate") is None
    trace = result["execution_trace"]
    assert any(e["type"] == "risk_metrics" for e in trace)
    assert not any(e["type"] == "human_gate" for e in trace)
