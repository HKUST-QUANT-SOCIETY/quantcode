"""AgentRunner route_gate + HumanGate interrupt 测试 — Day 4 尹一帆。

覆盖:
1. gate_tools 为空时 route_gate 节点不挂载
2. tool 不在 gate_tools 列表时 route_gate 跳过
3. LLM 调 check_gate 且 requires_human=True → 触发 interrupt
4. resume(approve) 后 Agent 继续调后续 tool
5. resume(reject) 后 Agent 跳到 finalize
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import tools.risk._register  # noqa: F401  触发 5 个 risk tool 注册
from tools.registry import registry as global_registry
from schemas.risk_profile import RiskProfile, RiskThresholds
from datetime import date


@pytest.fixture(autouse=True)
def _ensure_risk_registered():
    """保证每个测试前 5 个 risk tool 都注册了。

    全量测试时,test_mcp_server 的 _clean_registry fixture 会清空 registry
    并只 reload model,导致 risk tools 消失。本 fixture 在每个 gate 测试
    前重新 import tools.risk._register 重新注册(幂等)。
    """
    import importlib
    importlib.reload(tools.risk._register)
    yield


def _high_risk_profile_dict() -> dict:
    """构造 var_99 超 0.04 阈值的 RiskProfile dict(序列化后传给 check_gate)。"""
    profile = RiskProfile(
        strategy_id="test",
        as_of_date=date(2026, 7, 8),
        max_drawdown=0.05,
        position_limit=0.5,
        correlation_with_existing=0.3,
        capacity_estimate_usd=10_000_000.0,
        tail_risk_var_99=0.06,  # 超 0.04 阈值
    )
    return profile.model_dump(mode="json")


class _ScriptedLLM:
    """按预设顺序返 AIMessage,越界返 final。"""

    def __init__(self, responses: list[AIMessage], final: str = "[done]") -> None:
        self._responses = responses
        self._idx = 0
        self._final = final

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return AIMessage(content=self._final)


# ---------------------------------------------------------------------------
# 1. gate_tools 为空 → route_gate 节点不挂载
# ---------------------------------------------------------------------------


def test_route_gate_node_not_added_when_gate_tools_empty():
    """🟢Day 4 #A 验收:gate_tools=[] 时 AgentRunner 不挂载 route_gate 节点。

    通过 build() 后的 graph 节点集合断言不含 "gate"。
    """
    from runner.agent_engine import AgentRunner

    runner = AgentRunner(
        group="risk",
        model=_ScriptedLLM([]),
        checkpoint_db="/tmp/cp_test_route_gate_empty.db",
    )
    app = runner.build(skill_name=None, system_prompt="x")
    # 编译后 graph 的节点集合(graph.get_graph().nodes)
    nodes = set(app.get_graph().nodes.keys())
    assert "gate" not in nodes, f"gate_tools=[] 时不应有 gate 节点: {nodes}"


# ---------------------------------------------------------------------------
# 2. tool 不在 gate_tools 列表 → route_gate 跳过(no-op)
# ---------------------------------------------------------------------------


def test_route_gate_skipped_when_tool_not_in_gate_list(tmp_path):
    """🟢Day 4 #A 验收:LLM 调 read_blackboard(不在 gate_tools 列表)时,gating 不触发。

    gate_tools=["check_gate"],但 LLM 调的是 read_blackboard(其他 risk tool),
    AgentRunner 跑完后不应有 gate_decision 字段。
    """
    from runner.agent_engine import AgentRunner

    script = [
        AIMessage(
            content="",
            tool_calls=[{"name": "read_blackboard", "args": {"input_data": {"pr_number": 1}}, "id": "1"}],
        ),
        AIMessage(content="[done read_blackboard only]"),
    ]
    runner = AgentRunner(
        group="risk",
        model=_ScriptedLLM(script),
        gate_tools=["check_gate"],
        checkpoint_db=tmp_path / "cp.db",
    )
    final = runner.run(
        task="读 blackboard",
        skill_name=None,
        system_prompt="x",
        thread_id="t-1",
    )
    # 不应触发 gate(没调 check_gate)
    assert "gate_decision" not in final or final.get("gate_decision") is None
    # state 走完自然结束
    assert final.get("iterations", 0) >= 1


# ---------------------------------------------------------------------------
# 3. LLM 调 check_gate + requires_human=True → 触发 interrupt
# ---------------------------------------------------------------------------


def test_route_gate_triggers_interrupt_on_check_gate_high_risk(tmp_path):
    """🟢Day 4 #A 验收:LLM 调 check_gate 且返 requires_human=True → interrupt。

    LangGraph 0.2+ 不再抛 GraphInterrupt,而是把 interrupt 存在
    state['__interrupt__'] 字段。AgentRunner.run() 正常返回带 __interrupt__ 的 state。
    """
    from runner.agent_engine import AgentRunner

    # 让 LLM 调 read_blackboard → check_gate(high_risk profile)
    script = [
        AIMessage(
            content="",
            tool_calls=[{"name": "read_blackboard", "args": {"input_data": {"pr_number": 1}}, "id": "1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "check_gate",
                    "args": {"risk_profile": _high_risk_profile_dict()},
                    "id": "2",
                }
            ],
        ),
        AIMessage(content="[should not reach]"),
    ]
    runner = AgentRunner(
        group="risk",
        model=_ScriptedLLM(script),
        gate_tools=["check_gate"],
        checkpoint_db=tmp_path / "cp.db",
    )
    final = runner.run(
        task="risk check",
        skill_name=None,
        system_prompt="x",
        thread_id="t-interrupt",
    )
    # 验证:state 含 __interrupt__(LangGraph 0.2+ 行为)
    assert "__interrupt__" in final, f"expected __interrupt__ in state, got keys: {sorted(final.keys())}"
    interrupts = final.get("__interrupt__")
    assert interrupts, f"expected non-empty __interrupt__, got {interrupts}"
    # 🟢Day 4 #A 严格验收:interrupt payload 是 HumanGateInterruptPayload 格式
    interrupt_obj = interrupts[0]
    # LangGraph 0.2+ 的 Interrupt 对象有 .value 字段存 payload
    payload = getattr(interrupt_obj, "value", interrupt_obj)
    assert isinstance(payload, dict), f"interrupt payload 必须是 dict, got {type(payload)}"
    assert "gate_id" in payload, f"payload 缺 gate_id: {payload}"
    assert "message" in payload, f"payload 缺 message: {payload}"
    assert "reasons" in payload, f"payload 缺 reasons: {payload}"
    assert "risk_profile" in payload, f"payload 缺 risk_profile: {payload}"
    # reasons 应含 "tail_risk_var_99"(我传 0.06 > 0.04 阈值)
    assert "tail_risk_var_99" in payload["reasons"], (
        f"reasons 应含 'tail_risk_var_99', got {payload['reasons']}"
    )
    # decision 字段为 None(还没人审批)
    assert payload.get("decision") is None, f"decision 应为 None, got {payload.get('decision')}"
    # 验证:有 check_gate 的 ToolMessage(中断前工具已调过)
    has_check_gate = any(
        isinstance(m, ToolMessage) and m.name == "check_gate" for m in final.get("messages", [])
    )
    assert has_check_gate, "应有 check_gate 的 ToolMessage 在 messages 中"


# ---------------------------------------------------------------------------
# 4. resume(approve) → Agent 继续
# ---------------------------------------------------------------------------


def test_route_gate_approve_resumes_and_runs_subsequent_tools(tmp_path):
    """🟢Day 4 #A 验收:resume("approve") 后 Agent 继续调后续 tool(write_pr_comment)。

    这个测试跑 2 次 run:
    1. 第一次:让 check_gate 触发 interrupt(__interrupt__ 字段)
    2. 第二次:用 resume("approve") 恢复,期望 LLM 继续决策(可调 write_pr_comment 或 final)
    """
    from runner.agent_engine import AgentRunner

    script = [
        # 第一次 run:触发 interrupt
        AIMessage(
            content="",
            tool_calls=[{"name": "read_blackboard", "args": {"input_data": {"pr_number": 1}}, "id": "1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "check_gate",
                    "args": {"risk_profile": _high_risk_profile_dict()},
                    "id": "2",
                }
            ],
        ),
        # 第二次 run(resume): 继续 → 写 PR comment 或 final
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "write_pr_comment",
                    "args": {"risk_profile": {"strategy_id": "test", "var_99": 0.06}, "pr_number": 1, "head_sha": "abc"},
                    "id": "3",
                }
            ],
        ),
        AIMessage(content="[final]"),
    ]
    runner = AgentRunner(
        group="risk",
        model=_ScriptedLLM(script),
        gate_tools=["check_gate"],
        checkpoint_db=tmp_path / "cp.db",
    )
    # 第一次 run:触发 interrupt
    final_1 = runner.run(
        task="risk check",
        skill_name=None,
        system_prompt="x",
        thread_id="t-resume",
    )
    assert "__interrupt__" in final_1, f"第一次 run 应有 __interrupt__: {sorted(final_1.keys())}"

    # resume approve
    final = runner.resume("t-resume", "approve", skill_name=None, system_prompt="x")
    # 🟢Day 4 #A 严格验收:gate_decision 字段真存到 state
    assert final.get("gate_decision") == "approve", (
        f"expected gate_decision='approve', got {final.get('gate_decision')!r}"
    )
    # 🟢HumanGateInterruptPayload 持久化到 state
    payload = final.get("human_gate_payload")
    assert payload is not None, "human_gate_payload 应存到 state"
    assert payload.get("decision") == "approve", f"payload.decision 应='approve', got {payload}"
    assert payload.get("gate_id"), "payload.gate_id 非空"
    # resume 后 Agent 继续,验证 write_pr_comment 被调
    msgs = final.get("messages", [])
    has_write = any(
        isinstance(m, ToolMessage) and m.name == "write_pr_comment" for m in msgs
    )
    assert has_write, f"resume 后应有 write_pr_comment ToolMessage: {[m.name for m in msgs if isinstance(m, ToolMessage)]}"
    # 验证:有 check_gate 的 ToolMessage(说明 check_gate 跑过)
    has_check = any(
        isinstance(m, ToolMessage) and m.name == "check_gate" for m in msgs
    )
    assert has_check, "应有 check_gate 的 ToolMessage"
    # 验证:没有 __interrupt__(说明已恢复)
    assert "__interrupt__" not in final or not final.get("__interrupt__"), (
        f"resume 后应清空 __interrupt__, got {final.get('__interrupt__')}"
    )
