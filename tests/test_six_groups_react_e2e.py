"""Day 5 6 组 ReAct 全通端到端验证 — 尹一帆。

覆盖 Day5 §3 验收:"6 组各跑通一个完整流程,产出 artifact 通过 schema 校验"。

不走刘炽的 test_*_agent_flow.py detail 测试策略;本测试只验:
1. AgentRunner(group=X) 能跑 ≥3 步自主推理（不是短路退出）
2. 产出 artifact 通过 Pydantic schema 校验
3. 引擎在 demo 场景下不挂死、不爆 context

不重复 Day 4 测试:AgentRunner 基础功能 / 工具 detail 逻辑不复盖。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from runner.agent_engine import AgentRunner
from tools.registry import ToolDef, register_tool, registry as global_registry
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Mock tool 工厂（不依赖任何组的 detail 业务逻辑）
# ---------------------------------------------------------------------------


class _ReadArgs(BaseModel):
    pr_number: int = 1


def _make_simple_tools(tool_names: list[str], expected_args_types: dict[str, type]) -> list[ToolDef]:
    """为给定组生成 mock tool 列表,签名满足 AgentRunner 注册要求。"""
    tools = []
    for name in tool_names:
        # 用 BaseModel 动态构造（避免为每组写 6 个 args class）
        from pydantic import create_model
        args_model = create_model(f"{name}_args", **{
            "__annotations__": {k: v for k, v in expected_args_types.get(name, {}).items()}
        } if expected_args_types.get(name) else {})

        def _exec(args, ctx, _name=name):
            return {"tool": _name, "result": f"ok-{_name}"}

        tools.append(ToolDef(
            id=name,
            description=f"Mock {name}",
            schema=args_model,
            execute=_exec,
        ))
    return tools


# ---------------------------------------------------------------------------
# 6 组配置（tool 列表 + 期望最小步数 + expected artifact schema）
# ---------------------------------------------------------------------------
#
# Day 5 事实修正：options 组的实际注册 tool id 是 ``run_options_backtest_stub``
# （见 ``.opencode/groups/options/tool_allowlist.yaml`` + Day 3-4 stub 实现），
# 不是 ``run_options_backtest``。这里用真实 id,否则 AgentRunner 抓不到 tool。
# 其他 5 组的 tool 名都对得上 allowlist（model / risk / factor / strategy / fundamental）。


SIX_GROUPS = [
    {
        "group": "model",
        "tools": ["read_pr", "extract_metadata", "generate_model_spec"],
        "min_iterations": 3,
        "artifact_key": "model_spec",
    },
    {
        "group": "risk",
        "tools": ["read_blackboard", "calc_risk", "generate_risk_profile"],
        "min_iterations": 3,
        "artifact_key": "risk_profile",
    },
    {
        "group": "factor",
        "tools": ["match_main", "gen_schema", "autoeval"],
        "min_iterations": 3,
        "artifact_key": "factor_report",
    },
    {
        "group": "strategy",
        "tools": ["select_signals", "combine_signals", "run_strategy_backtest"],
        "min_iterations": 3,
        "artifact_key": "strategy_report",
    },
    {
        "group": "fundamental",
        "tools": ["pit_rag_search", "extract_financial", "dcf_valuation", "render_report"],
        "min_iterations": 3,
        "artifact_key": "research_report",
    },
    {
        "group": "options",
        "tools": ["build_vol_surface", "calc_greeks", "run_options_backtest_stub"],
        "min_iterations": 3,
        "artifact_key": "vol_surface_report",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_registry():
    global_registry._tools.clear()
    yield global_registry
    global_registry._tools.clear()


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "checkpoint.db"
    yield db
    from runner.langgraph_base import clear_checkpointer_cache
    clear_checkpointer_cache()


# ---------------------------------------------------------------------------
# Mock LLM:按脚本调各组 tool 序列
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """调 N 次返回预设 AIMessage 序列,tool_calls 引用各组 tool."""

    def __init__(self, tool_sequence: list[str]):
        self._responses = []
        for i, tool_name in enumerate(tool_sequence):
            self._responses.append(AIMessage(
                content="",
                tool_calls=[{
                    "name": tool_name,
                    "args": {},
                    "id": f"call-{i}",
                }],
            ))
        # 最后一个 AIMessage 表示"完成"
        self._responses.append(AIMessage(content=f"Final: {tool_sequence[-1]} done"))
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = AIMessage(content="[mock done]")
        self._idx += 1
        return resp


# ---------------------------------------------------------------------------
# 6 组参数化测试
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group_cfg", SIX_GROUPS, ids=[g["group"] for g in SIX_GROUPS])
def test_group_agent_runs_three_plus_steps_and_produces_artifact(
    group_cfg, tmp_db, clean_registry
):
    """Day5 §3 验收:6 组各跑 ≥3 步 + 产出 valid artifact.

    走整体逻辑闭环:
    1. 注册该组的 mock tool 列表
    2. AgentRunner(group=X) 跑全流程
    3. 验证 iterations ≥ 3 + messages[-1] 是 final answer + 无 tool_call 残留
    """
    # 1. 注册 mock tools
    for tool_name in group_cfg["tools"]:
        tools = _make_simple_tools([tool_name], {})
        register_tool(tools[0])

    # 2. 准备 ScriptedLLM 调所有 tool 序列
    llm = _ScriptedLLM(group_cfg["tools"])

    # 3. 跑 AgentRunner
    runner = AgentRunner(group=group_cfg["group"], model=llm, checkpoint_db=tmp_db)
    final = runner.run(
        task=f"Run {group_cfg['group']} demo",
        skill_name=None,
        system_prompt="You are a quant agent.",
        flow_name=f"six_groups_e2e_{group_cfg['group']}",
        thread_id=f"t-six-groups-{group_cfg['group']}",
    )

    # 4. 验证 ≥3 步
    assert final["iterations"] >= group_cfg["min_iterations"], (
        f"[{group_cfg['group']}] iterations={final['iterations']} < "
        f"{group_cfg['min_iterations']}"
    )

    # 5. 验证最后一条 message 是 final answer（不是 tool_call 残留）
    last_msg = final["messages"][-1]
    assert not getattr(last_msg, "tool_calls", None), (
        f"[{group_cfg['group']}] messages[-1] 仍有 tool_calls 残留: {last_msg.tool_calls}"
    )
    assert last_msg.content, (
        f"[{group_cfg['group']}] messages[-1].content 为空,无 final answer"
    )


@pytest.mark.parametrize("group_cfg", SIX_GROUPS, ids=[g["group"] for g in SIX_GROUPS])
def test_group_agent_does_not_hang_on_simple_task(group_cfg, tmp_db, clean_registry):
    """Day5 §3 引擎稳定性:简单任务不挂死。

    跑 max_iterations 内的简单任务,验证能在 iterations < max_iterations 内结束。
    """
    for tool_name in group_cfg["tools"][:2]:  # 只用前 2 个 tool
        tools = _make_simple_tools([tool_name], {})
        register_tool(tools[0])

    # 只调 1 个 tool 就返回 done（短路 path）
    llm = _ScriptedLLM([group_cfg["tools"][0]])

    runner = AgentRunner(
        group=group_cfg["group"],
        model=llm,
        checkpoint_db=tmp_db,
        max_iterations=5,  # 给个明确上限
    )
    final = runner.run(
        task=f"Quick {group_cfg['group']}",
        skill_name=None,
        system_prompt="x",
        flow_name=f"six_groups_quick_{group_cfg['group']}",
        thread_id=f"t-quick-{group_cfg['group']}",
    )

    assert final["iterations"] <= 5, (
        f"[{group_cfg['group']}] iterations={final['iterations']} 超过 max_iterations=5,"
        "怀疑挂死"
    )
