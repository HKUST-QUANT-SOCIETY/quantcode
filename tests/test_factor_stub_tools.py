"""factor stub tool 测试 — Day 4 尹一帆。

覆盖:
1. 3 个 tool 注册进 registry
2. stub 返回结构正确
3. autoeval 跟 flows.factor_autoeval.MOCK_AUTOEVAL_PAYLOAD_V1 共享常量键集合一致
4. AgentRunner(group="factor") 跑通 3 步自主推理
5. factor group allowlist 解析 ≥3 个 factor tool
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

import tools.factor._register  # noqa: F401  触发 3 个 stub tool 注册
from tools.registry import registry as global_registry


@pytest.fixture(autouse=True)
def _ensure_factor_registered():
    """保证每个测试前 factor 3 个 tool 都注册了。

    全量测试时,test_mcp_server 的 _clean_registry fixture 会清空 registry
    并只 reload model,导致 factor tools 消失。本 fixture 在每个 factor 测试
    前重新 import tools.factor._register 重新注册(幂等)。
    """
    import importlib
    importlib.reload(tools.factor._register)
    yield


# ---------------------------------------------------------------------------
# 1. 3 个 tool 注册
# ---------------------------------------------------------------------------


def test_factor_tools_registered():
    """3 个 stub tool 都注册进全局 registry,get 不抛 KeyError。"""
    for tid in ("match_main", "gen_schema", "autoeval"):
        t = global_registry.get(tid)
        assert t.id == tid
        assert t.description  # 非空
        assert t.schema is not None
        assert callable(t.execute)


# ---------------------------------------------------------------------------
# 2. stub 返回结构
# ---------------------------------------------------------------------------


def test_match_main_stub_returns_expected_shape():
    """match_main stub 返回 {compatible, suggested_fields, notes} 三键。"""
    t = global_registry.get("match_main")
    # 模拟 registry.call 的参数验证路径
    validated = t.schema(idea="PB-ROE 季度再平衡")
    out = t.execute(validated, ctx={})
    assert isinstance(out, dict)
    assert out["compatible"] is True
    assert isinstance(out["suggested_fields"], list)
    assert len(out["suggested_fields"]) > 0
    assert "notes" in out


def test_gen_schema_stub_returns_expected_shape():
    """gen_schema stub 返回 {name, formula, fields, rebalance} 四键。"""
    t = global_registry.get("gen_schema")
    validated = t.schema(
        idea="PB-ROE 季度再平衡",
        match_result={"compatible": True, "suggested_fields": ["pb", "roe"]},
    )
    out = t.execute(validated, ctx={})
    assert isinstance(out, dict)
    assert "name" in out
    assert "formula" in out
    assert "fields" in out
    assert out["fields"] == ["pb", "roe"]
    assert "rebalance" in out


# ---------------------------------------------------------------------------
# 3. autoeval stub 跟 flows.MOCK_AUTOEVAL_PAYLOAD_V1 共享常量键集合一致
# ---------------------------------------------------------------------------


def test_autoeval_payload_parity_with_factor_autoeval_flows():
    """🟢Day 4 #B 验收:消除双维护。

    autoeval_stub 跟 flows/factor_autoeval.py:_mock_autoeval_result 必须用同一个常量,
    两边硬编码字段集合保持一致(任一边增字段,另一边必须同步)。
    """
    from flows.factor_autoeval import MOCK_AUTOEVAL_PAYLOAD_V1
    from tools.factor.autoeval_stub import autoeval_tool, AutoevalArgs

    # stub 走 execute → 返 dict
    stub_out = autoeval_tool.execute(AutoevalArgs(spec={"name": "x"}), ctx={})

    # 字段集合一致(顺序无关)
    assert set(stub_out.keys()) == set(MOCK_AUTOEVAL_PAYLOAD_V1.keys()), (
        f"字段漂移! stub={set(stub_out.keys()) - set(MOCK_AUTOEVAL_PAYLOAD_V1.keys())}, "
        f"flows={set(MOCK_AUTOEVAL_PAYLOAD_V1.keys()) - set(stub_out.keys())}"
    )


# ---------------------------------------------------------------------------
# 4. AgentRunner(group="factor") 跑通 3 步自主推理
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """按预设顺序返 AIMessage,最后返 done。

    ⚠️ Caveat(Day 4 严格性):
    本 mock **不是真 LLM 决策**。它严格按预设顺序返 AIMessage,本质是 scripted
    pipeline 用 AgentRunner 包装。"3 步自主推理"在本测试里只验证:
    1. 工具链顺序可达(match_main → gen_schema → autoeval 都能被工具节点处理)
    2. AgentRunner 状态机正确推进(messages 累积 / iterations 计数)

    **不验证**:LLM 真看到 state 后"自主决定"下一步调什么。生产环境用真 LLM 时
    决策质量需要单独评测,MockLLM 测不到。本测试通过 ≠ 生产可用,只说明架构层
    把脚本流程接到了 AgentRunner。
    """

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = responses
        self._idx = 0

    def __call__(self, messages, tools=None):
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return AIMessage(content="[mock default done]")


def test_agent_runner_factor_react_three_steps(tmp_path):
    """🟢Day 4 #B 验收:factor 经 AgentRunner 跑通 match_main → gen_schema → autoeval。

    3 步 tool_call,LLM 自主决定顺序,assert state 含 3 ToolMessage + iterations=2。
    """
    from runner.agent_engine import AgentRunner

    script = [
        AIMessage(
            content="",
            tool_calls=[{"name": "match_main", "args": {"idea": "PB-ROE"}, "id": "1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "gen_schema",
                    "args": {
                        "idea": "PB-ROE",
                        "match_result": {"compatible": True, "suggested_fields": ["pb", "roe"]},
                    },
                    "id": "2",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "autoeval",
                    "args": {"spec": {"name": "pb_roe"}},
                    "id": "3",
                }
            ],
        ),
        AIMessage(content="[done]"),
    ]

    runner = AgentRunner(
        group="factor",
        model=_ScriptedLLM(script),
        checkpoint_db=tmp_path / "cp.db",
    )
    final = runner.run(
        task="生成 PB-ROE 季度再平衡因子",
        skill_name=None,
        system_prompt="你是一个因子生成助手",
        thread_id="t-factor-3step",
    )

    # 消息序列:1 Human + 4 AIMessage + 3 ToolMessage = 8 条
    msgs = final.get("messages", [])
    from langchain_core.messages import AIMessage as AI, HumanMessage as HU, ToolMessage as TM

    n_ai = sum(1 for m in msgs if isinstance(m, AI))
    n_human = sum(1 for m in msgs if isinstance(m, HU))
    n_tool = sum(1 for m in msgs if isinstance(m, TM))
    assert n_human == 1, f"expected 1 HumanMessage, got {n_human}"
    assert n_ai == 4, f"expected 4 AIMessage (3 tool_call + 1 done), got {n_ai}"
    assert n_tool == 3, f"expected 3 ToolMessage, got {n_tool}"
    # iterations 应为 4(每次 LLM 调用 +1,共 4 次调用)
    assert final.get("iterations", 0) == 4, f"iterations expected 4, got {final.get('iterations')}"


# ---------------------------------------------------------------------------
# 5. factor group allowlist 解析
# ---------------------------------------------------------------------------


def test_factor_group_allowlist_resolves_three_tools():
    """🟢Day 4 #B 验收:.opencode/groups/factor/tool_allowlist.yaml 包含 3 个 factor tool。

    现有 allowlist 已有 4 个共享工具(search_memory/read_file/write_file/bash),
    加上 Day 4 新增 3 个 factor tool,get_tools_for_group("factor") 至少 3 个 factor tool。
    """
    tools = global_registry.get_tools_for_group("factor")
    tool_ids = {t.id for t in tools}
    assert {"match_main", "gen_schema", "autoeval"} <= tool_ids, (
        f"factor allowlist 缺 3 个 factor tool: {tool_ids}"
    )
    # 至少 3 个 factor tool(共享 4 个未必注册到 registry,不强求)
    factor_count = len(tool_ids & {"match_main", "gen_schema", "autoeval"})
    assert factor_count == 3
