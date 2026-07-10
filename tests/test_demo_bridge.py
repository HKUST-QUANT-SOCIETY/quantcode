"""demo_bridge 测试 — Day 5 Lead。

验证 bridge 渲染 execution_trace + 两阶段 HumanGate + JSONL 模式，
且走的是与 MCP 入口同一条 _run_agent_execute 链路。
"""
from __future__ import annotations

import json

import pytest

from runner import demo_bridge


def test_print_event_human_readable(capsys):
    demo_bridge._print_event(
        {"type": "tool_call", "data": {"tool_name": "calc_risk"}}, jsonl=False
    )
    out = capsys.readouterr().out
    assert "tool_call" in out
    assert "calc_risk" in out


def test_print_event_jsonl(capsys):
    ev = {"type": "llm_thought", "data": {"text": "thinking"}}
    demo_bridge._print_event(ev, jsonl=True)
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["type"] == "llm_thought"


def test_render_result_jsonl_emits_result_summary(capsys):
    result = {
        "status": "completed",
        "thread_id": "t-1",
        "artifacts": ["a.json"],
        "execution_trace": [
            {"type": "agent_start", "data": {}},
            {"type": "agent_end", "data": {}},
        ],
    }
    demo_bridge._render_result(result, jsonl=True)
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().split("\n")]
    types = [x["type"] for x in lines]
    assert "agent_start" in types
    assert "_result" in types
    assert lines[-1]["status"] == "completed"


def test_main_start_mode_renders(monkeypatch, capsys):
    """start 模式：mock _run_agent_execute 返回 completed，bridge 应渲染 trace。"""
    fake = {
        "status": "completed",
        "thread_id": "t-x",
        "artifacts": [],
        "execution_trace": [
            {"type": "agent_start", "data": {}},
            {"type": "tool_call", "data": {"tool_name": "match_main"}},
            {"type": "agent_end", "data": {}},
        ],
    }
    monkeypatch.setattr(
        "runner.agent_mcp_tool._run_agent_execute", lambda args, ctx: fake
    )
    rc = demo_bridge.main(["--group", "factor", "--task", "测因子"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "match_main" in out
    assert "completed" in out


def test_main_human_gate_two_phase(monkeypatch, capsys):
    """撞 HumanGate → auto-approve → 第二次调用返回 completed。"""
    calls = {"n": 0}

    def _fake(args, ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "status": "waiting_for_human",
                "thread_id": "t-gate",
                "gate": {"reasons": ["max_drawdown"]},
                "execution_trace": [{"type": "human_gate", "data": {}}],
            }
        return {
            "status": "completed",
            "thread_id": "t-gate",
            "artifacts": ["risk.json"],
            "execution_trace": [{"type": "agent_end", "data": {}}],
        }

    monkeypatch.setattr("runner.agent_mcp_tool._run_agent_execute", _fake)
    rc = demo_bridge.main(
        ["--group", "risk", "--skill", "risk-gate", "--task", "high_risk", "--auto-approve"]
    )
    assert rc == 0
    assert calls["n"] == 2  # start + resume
    out = capsys.readouterr().out
    assert "HumanGate" in out
    assert "completed" in out
