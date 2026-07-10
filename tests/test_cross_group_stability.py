"""Day 5 跨组流引擎稳定性回归 — 尹一帆。

目标（Day5 §3 "引擎稳定性"）：
- model→risk 长任务不爆 context、不挂死（factor→strategy 结构同源，引擎与组无关，详 Task 9）。
- 验证 AgentRunner 在 max_iterations 内结束、messages 数量合理、retry 包装生效。

按 Task 9 模式（test_six_groups_react_e2e.py）使用隔离 mock tool，
不污染 test_risk_flow.py 的 LangGraph 流程测试，也不依赖真实 BlackboardService。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import create_model

from runner.agent_engine import AgentRunner
from tools.registry import ToolDef, register_tool, registry as global_registry


# ---------------------------------------------------------------------------
# Mock tool 工厂（隔离模式，不依赖业务 tool 的 schema）
# ---------------------------------------------------------------------------


def _make_mock_tools(tool_names: list[str]) -> list[ToolDef]:
    """为给定名称生成 mock ToolDef 列表，使用空 args schema（覆盖长任务场景）。"""
    tools = []
    for name in tool_names:
        # 空 schema — LLM 可任意 args 调用，模拟长任务下 tool 的鲁棒性
        args_model = create_model(f"{name}_mock_args")

        def _exec(args, ctx, _name=name):
            return {"tool": _name, "result": f"ok-{_name}"}

        tools.append(ToolDef(
            id=name,
            description=f"Mock {name} for cross-group stability test",
            schema=args_model,
            execute=_exec,
        ))
    return tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_registry():
    """清空全局 registry 后再交还，确保测试间隔离。"""
    global_registry._tools.clear()
    yield global_registry
    global_registry._tools.clear()


@pytest.fixture
def tmp_db(tmp_path):
    """提供独立的 checkpoint DB，yield 后清理 checkpointer 缓存。"""
    db = tmp_path / "checkpoint.db"
    yield db
    from runner.langgraph_base import clear_checkpointer_cache
    clear_checkpointer_cache()


# ---------------------------------------------------------------------------
# Mock LLM:模拟跨组长任务（5 次 tool_call + 1 次 final）
# ---------------------------------------------------------------------------


class _LongScriptedLLM:
    """模拟 model→risk 跨组长任务:5 次 tool_call,然后 final answer。

    场景:model 跑完 → write_blackboard → trigger_risk_flow,
          risk Agent 被触发 → read_blackboard → calc_risk × 4。
    """

    def __init__(self) -> None:
        self._responses = [
            AIMessage(content="", tool_calls=[
                {"name": "read_blackboard", "args": {}, "id": "1"},
            ]),
            AIMessage(content="", tool_calls=[
                {"name": "calc_risk", "args": {"x": 1}, "id": "2"},
            ]),
            AIMessage(content="", tool_calls=[
                {"name": "calc_risk", "args": {"x": 2}, "id": "3"},
            ]),
            AIMessage(content="", tool_calls=[
                {"name": "calc_risk", "args": {"x": 3}, "id": "4"},
            ]),
            AIMessage(content="", tool_calls=[
                {"name": "calc_risk", "args": {"x": 4}, "id": "5"},
            ]),
            AIMessage(content="Final cross-group done"),
        ]
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="[done]")
        self._idx += 1
        return resp


# ---------------------------------------------------------------------------
# 稳定性测试
# ---------------------------------------------------------------------------


def test_cross_group_flow_engine_stability_under_long_task(tmp_db, clean_registry):
    """Day5 §3 引擎稳定性:跨组长任务不爆 context、不挂死。

    场景:
    - risk Agent 跑完 5 步 tool_call（read_blackboard + calc_risk × 4）→ final answer
    - 验证:
      1. iterations < max_iterations（说明正常结束而非撞 max 挂死）
      2. messages 数量合理（不爆 context）
      3. messages[-1] 无 tool_calls 残留
      4. retry 包装下 LLM 至少调 5 次
    """
    # 1. 注册 risk 组的 mock tools（read_blackboard + calc_risk）
    for tool in _make_mock_tools(["read_blackboard", "calc_risk"]):
        register_tool(tool)

    # 2. 准备 5 步 scripted LLM
    llm = _LongScriptedLLM()

    # 3. 跑 risk Agent（接力 model 后的 risk 流）
    runner = AgentRunner(
        group="risk",
        model=llm,
        checkpoint_db=tmp_db,
        max_iterations=10,
        retry_max_retries=2,  # 启用 retry 包装
    )
    final = runner.run(
        task="Long cross-group stability test",
        skill_name=None,
        system_prompt="x",
        flow_name="cross_group_stability",
        thread_id="t-cross-stab-1",
    )

    # 稳定性断言 1:iterations < max_iterations（用 < 不用 <=，避免 set max=10 → 0..10 都过的 tautology）
    assert final["iterations"] < 10, (
        f"iterations={final['iterations']} 达到 max_iterations=10,怀疑挂死 / runaway loop"
    )

    # 稳定性断言 2:messages 数量合理（不爆 context）
    #    5 步 tool_call → 大约 5 AIMessage + 5 ToolMessage = ~10 条
    #    加 RLHF/HumanMessage 等元数据，控制在 50 内远不爆
    msg_count = len(final["messages"])
    assert msg_count < 20, (
        f"messages 数量 {msg_count} 过多,怀疑 context 爆掉"
    )

    # 稳定性断言 3:最后一条 message 是 final answer（不残留 tool_call）
    last_msg = final["messages"][-1]
    assert not getattr(last_msg, "tool_calls", None), (
        f"messages[-1] 仍有 tool_calls 残留: {getattr(last_msg, 'tool_calls', None)}"
    )
    assert last_msg.content, (
        "messages[-1].content 为空,无 final answer"
    )

    # 稳定性断言 4:retry 包装生效（retry_max_retries>0 时 model 应被 RetryWrapper 包）
    #    LongScriptedLLM 至少被调 5 次（5 次 tool_call 后 LLM 再调一次返回 final）
    assert hasattr(runner.model, "stats"), (
        "retry_max_retries>0 时 AgentRunner.model 应该是 RetryWrapper"
    )
    assert runner.model.__class__.__name__ == "RetryWrapper", (
        f"retry_max_retries>0 时 AgentRunner.model 应是 RetryWrapper,实际 {runner.model.__class__.__name__}"
    )
    assert runner.model.stats.total_calls >= 5, (
        f"retry 包装下,LLM 应至少调 5 次,实际 total_calls={runner.model.stats.total_calls}"
    )
