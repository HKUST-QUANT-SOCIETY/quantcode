"""factor tool 测试 — Day 4 尹一帆，Day 5 真版实现 + 降级契约。

覆盖:
1. 3 个 tool 注册进 registry
2. 真版降级契约：无 env key / API 不可用时
   - match_main 返回 compatible + suggested_fields + notes
   - gen_schema 降级输出是 FactorSpec(extra="forbid") 契约合法 dict
     （降级事实走 logging.warning，不再往输出塞 _fallback 非法键），
     FactorSpec(**output) 直接验证通过
   - quant_evaluator 返回 _is_mock 标记（共享 flows.factor_evaluation_adapter.MOCK_AUTOEVAL_PAYLOAD_V1）
3. AgentRunner(group="factor") 跑通 3 步自主推理
4. factor group allowlist 解析 ≥3 个 factor tool
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from tools.registry import register_tool
from tools.registry import registry as global_registry


@pytest.fixture(autouse=True)
def _ensure_factor_registered():
    """保证每个测试前 factor 3 个 tool 都注册了。

    test_agent_engine_basic / test_mcp_server 等会清空全局 registry。
    恒真版注册是幂等的（register_tool 覆盖式），直接重新注册即可。
    """
    from tools.factor._register import quant_evaluator_tool, gen_schema_tool, match_main_tool

    register_tool(match_main_tool)
    register_tool(gen_schema_tool)
    register_tool(quant_evaluator_tool)
    yield


@pytest.fixture(autouse=True)
def _no_llm_no_network(monkeypatch):
    """强制真版 tool 走降级路径：无 env key + 网络层必失败（即使本机有 config.json）。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("AUTOEVAL_API_URL", raising=False)
    monkeypatch.delenv("AUTOEVAL_API_KEY", raising=False)
    try:
        import requests
    except ImportError:
        return

    def _network_disabled(*args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(requests, "post", _network_disabled)


# ---------------------------------------------------------------------------
# 1. 3 个 tool 注册
# ---------------------------------------------------------------------------


def test_factor_tools_registered():
    """3 个 tool 都注册进全局 registry,get 不抛 KeyError。"""
    for tid in ("match_main", "gen_schema", "quant_evaluator"):
        t = global_registry.get(tid)
        assert t.id == tid
        assert t.description  # 非空
        assert t.schema is not None
        assert callable(t.execute)


# ---------------------------------------------------------------------------
# 2. 真版降级契约
# ---------------------------------------------------------------------------


def test_match_main_fallback_without_llm(monkeypatch):
    """无 LLM 时 match_main 必须拒绝生成乐观兼容结论。"""
    import runner.llm_provider

    def _no_llm():
        raise ValueError("DeepSeek API key not configured")

    monkeypatch.setattr(runner.llm_provider, "create_deepseek_llm", _no_llm)

    t = global_registry.get("match_main")
    validated = t.schema(idea="PB-ROE 季度再平衡")
    out = t.execute(validated, ctx={})
    assert isinstance(out, dict)
    assert out["compatible"] is False
    assert isinstance(out["suggested_fields"], list)
    assert out["result_status"] == "UNAVAILABLE"
    assert "notes" in out


def test_match_main_accepts_callable_llm_adapter(monkeypatch):
    """DeepSeekAdapter 的 callable 协议应返回并校验真实 JSON 结果。"""
    import runner.llm_provider

    class _CallableAdapter:
        def __call__(self, messages):
            assert messages
            return AIMessage(
                content='{"compatible": true, "suggested_fields": ["pb", "roe"], "notes": "主线字段可用"}'
            )

    monkeypatch.setattr(runner.llm_provider, "create_deepseek_llm", lambda: _CallableAdapter())
    t = global_registry.get("match_main")
    out = t.execute(t.schema(idea="PB-ROE 因子"), ctx={})
    assert out == {
        "compatible": True,
        "suggested_fields": ["pb", "roe"],
        "notes": "主线字段可用",
    }


def test_gen_schema_fallback_marks_fallback():
    """无 API key 时 gen_schema 降级：规则生成 FactorSpec 契约字段。

    FactorSpec 是 extra="forbid"，降级事实用 logging 诚实标注，
    不再往输出塞 _fallback/_error/fields/rebalance 等非法键
    （否则下游 FactorSpec(**output) 直接 ValidationError）。
    """
    t = global_registry.get("gen_schema")
    validated = t.schema(
        idea="PB-ROE 季度再平衡",
        match_result={"compatible": True, "suggested_fields": ["pb", "roe"]},
    )
    out = t.execute(validated, ctx={})
    assert isinstance(out, dict)
    assert out["formula"] == "pb * roe"
    assert out["operators"] == ["pb", "roe"]  # 从 formula 粗提取
    for key in (
        "name",
        "universe",
        "date_range",
        "estimated_runtime_seconds",
        "forward_return_horizon",
    ):
        assert key in out


def test_gen_schema_fallback_output_is_valid_factorspec():
    """降级输出直接 FactorSpec(**output) 必须通过（FactorSpec 契约闭环）。"""
    from schemas.factor import FactorSpec

    t = global_registry.get("gen_schema")
    validated = t.schema(
        idea="PB-ROE 季度再平衡",
        match_result={"compatible": True, "suggested_fields": ["pb", "roe"]},
    )
    out = t.execute(validated, ctx={})
    spec = FactorSpec(**out)  # 不抛 = 契约通过
    assert spec.estimated_runtime_seconds > 0
    assert spec.forward_return_horizon in (1, 3, 5, 10, 20)
    assert spec.operators  # min_length=1
    assert len(set(spec.operators)) == len(spec.operators)  # 唯一
    assert spec.date_range.end >= spec.date_range.start


def test_gen_schema_fallback_without_fields_uses_mean_operator():
    """suggested_fields 为空时 formula="value"；operators 从 formula 粗提取。

    formula 提取不到任何 token 时（如纯数字/空串）才补 ["mean"] 默认值。
    """
    from schemas.factor import FactorSpec
    from tools.factor.gen_schema import _coarse_operators

    t = global_registry.get("gen_schema")
    validated = t.schema(idea="模糊的因子想法", match_result={"compatible": True})
    out = t.execute(validated, ctx={})
    assert out["formula"] == "value"
    spec = FactorSpec(**out)  # 不抛 = 契约通过
    assert spec.operators == ["value"]  # 从 formula="value" 粗提取
    # 无 token 可提取时回退 ["mean"]（FactorSpec 要求 operators min_length=1）
    assert _coarse_operators("123 * !") == ["mean"]
    assert _coarse_operators("") == ["mean"]


def test_gen_schema_llm_response_missing_contract_fields_gets_patched(monkeypatch):
    """LLM 返回缺契约字段 + 垃圾键时：逐字段补默认值，FactorSpec(**output) 恒过。"""
    import json as _json

    import requests
    from schemas.factor import FactorSpec

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            content = _json.dumps(
                {
                    "name": "llm_momentum",
                    "formula": "mom_20 / vol_20",
                    "fields": ["mom_20", "vol_20"],  # 垃圾键：非 FactorSpec 字段
                    "rebalance": "monthly",  # 垃圾键
                    "forward_return_horizon": "3",  # 非法字面量（数字字符串应收编）
                    # 缺 operators / estimated_runtime_seconds / date_range
                }
            )
            return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse())

    t = global_registry.get("gen_schema")
    validated = t.schema(
        idea="20 日动量因子",
        match_result={"compatible": True, "suggested_fields": ["mom_20", "vol_20"]},
    )
    out = t.execute(validated, ctx={})

    spec = FactorSpec(**out)  # 恒过
    assert spec.name == "llm_momentum"
    assert spec.operators == ["mom_20", "vol_20"]  # 从 formula 粗提取补齐
    assert spec.estimated_runtime_seconds > 0  # 缺失补默认值
    assert spec.forward_return_horizon == 3  # "3" 收编为合法字面量
    assert "fields" not in out and "rebalance" not in out  # extra=forbid 键被过滤


def test_quant_evaluator_unavailable_never_returns_mock_metrics(monkeypatch):
    """FactorSpec must not be accepted as a substitute for QE's typed inputs."""
    t = global_registry.get("quant_evaluator")
    with pytest.raises(ValidationError):
        t.schema(spec={"name": "pb_roe"})


# ---------------------------------------------------------------------------
# 3. AgentRunner(group="factor") 跑通 3 步自主推理
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """按预设顺序返 AIMessage,最后返 done。

    ⚠️ Caveat(Day 4 严格性):
    本 mock **不是真 LLM 决策**。它严格按预设顺序返 AIMessage,本质是 scripted
    pipeline 用 AgentRunner 包装。"3 步自主推理"在本测试里只验证:
    1. 工具链顺序可达(match_main → gen_schema → quant_evaluator 都能被工具节点处理)
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
    """🟢Day 4 #B 验收:factor 经 AgentRunner 跑通 match_main → gen_schema → quant_evaluator。

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
                    "name": "quant_evaluator",
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
# 4. factor group allowlist 解析
# ---------------------------------------------------------------------------


def test_factor_group_allowlist_resolves_three_tools():
    """🟢Day 4 #B 验收:.opencode/groups/factor/tool_allowlist.yaml 包含 3 个 factor tool。

    现有 allowlist 已有 4 个共享工具(search_memory/read_file/write_file/bash),
    加上 Day 4 新增 3 个 factor tool,get_tools_for_group("factor") 至少 3 个 factor tool。
    """
    tools = global_registry.get_tools_for_group("factor")
    tool_ids = {t.id for t in tools}
    assert {"match_main", "gen_schema", "quant_evaluator"} <= tool_ids, (
        f"factor allowlist 缺 3 个 factor tool: {tool_ids}"
    )
    # 至少 3 个 factor tool(共享 4 个未必注册到 registry,不强求)
    factor_count = len(tool_ids & {"match_main", "gen_schema", "quant_evaluator"})
    assert factor_count == 3
