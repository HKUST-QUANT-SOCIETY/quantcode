"""Tests for the model group's 5 mock tools — Day 3 尹一帆。

覆盖：
- import 副作用 ``tools.model._register`` 把 5 个 tool 全部注册进全局 registry
- 每个 tool 通过 ``registry.call(tool_id, args)`` 能正常执行并返回约定结构
- schema 校验：缺字段 / 类型错会被 registry 转成 ``ValueError``
- dedupe 副作用：``write_blackboard`` / ``trigger_risk_flow`` 在窗口内
  对同一 key 返回缓存结果
"""
from __future__ import annotations

import re

import pytest

from tools.registry import registry

# 让 ``tools.model._register`` 的 import 副作用把所有 5 个 tool 注册进去
import tools.model._register  # noqa: F401
from tools.model.extract_metadata import extract_metadata_tool
from tools.model.generate_model_spec import generate_model_spec_tool
from tools.model.read_pr import read_pr_tool
from tools.model.trigger_risk_flow import trigger_risk_flow_tool
from tools.model.write_blackboard import write_blackboard_tool


EXPECTED_TOOL_IDS = {
    "read_pr",
    "extract_metadata",
    "generate_model_spec",
    "write_blackboard",
    "trigger_risk_flow",
}


@pytest.fixture(autouse=True)
def _ensure_model_tools_registered():
    """确保 5 个 model tool 已注册，防止被其他 test 的 clean_registry 清掉。

    其他测试文件用 ``registry._tools.clear()`` 清空，模块级 import 只跑一次，
    所以需要每次 test 前显式 reload 一次。
    """
    import importlib

    import tools.model._register  # noqa: F401

    importlib.reload(tools.model._register)
    yield


# ---------------------------------------------------------------------------
# 注册相关
# ---------------------------------------------------------------------------


def test_model_tools_all_registered():
    """import 副作用应把全部 5 个 model tool 注册进 registry。"""
    assert EXPECTED_TOOL_IDS.issubset(set(registry.list_ids()))


def test_each_tool_def_has_required_fields():
    """每个 tool 的 ToolDef 应当填充 id/description/schema/execute 四个必填字段。"""
    for tool in (
        read_pr_tool,
        extract_metadata_tool,
        generate_model_spec_tool,
        write_blackboard_tool,
        trigger_risk_flow_tool,
    ):
        assert tool.id
        assert tool.description
        assert tool.schema is not None
        assert callable(tool.execute)


# ---------------------------------------------------------------------------
# read_pr
# ---------------------------------------------------------------------------


def test_read_pr_returns_mock_diff():
    result = registry.call("read_pr", {"pr_number": 42})
    assert result["pr_number"] == 42
    assert "fake line 42" in result["diff"]
    assert result["title"] == "[MOCK] PR #42"
    assert result["author"] == "mock-user"


def test_read_pr_validates_pr_number_type():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("read_pr", {"pr_number": "not-an-int"})


def test_read_pr_requires_pr_number():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("read_pr", {})


# ---------------------------------------------------------------------------
# extract_metadata
# ---------------------------------------------------------------------------


def test_extract_metadata_parses_known_fields():
    diff = (
        "TICKER: AAPL\n"
        "FACTOR_NAME: momentum_20d\n"
        "FACTOR_TYPE: alpha\n"
        "DATE_RANGE: 2021-01-01..2023-12-31\n"
    )
    result = registry.call("extract_metadata", {"diff": diff})
    assert result == {
        "ticker": "AAPL",
        "factor_name": "momentum_20d",
        "factor_type": "alpha",
        "date_range": {"start": "2021-01-01", "end": "2023-12-31"},
    }


def test_extract_metadata_defaults_for_missing_fields():
    result = registry.call("extract_metadata", {"diff": "no markers here"})
    assert result["ticker"] == "UNKNOWN"
    assert result["factor_name"] == "unknown_factor"
    assert result["factor_type"] == "alpha"
    assert result["date_range"] == {"start": "2020-01-01", "end": "2024-12-31"}


def test_extract_metadata_requires_diff():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("extract_metadata", {})


# ---------------------------------------------------------------------------
# generate_model_spec
# ---------------------------------------------------------------------------


def test_generate_model_spec_returns_expected_shape():
    metadata = {
        "ticker": "AAPL",
        "factor_name": "momentum_20d",
        "factor_type": "alpha",
        "date_range": {"start": "2022-01-01", "end": "2024-06-30"},
    }
    result = registry.call("generate_model_spec", {"metadata": metadata})
    assert result["model_type"] == "lightgbm"
    assert result["training_window"] == {"start": "2022-01-01", "end": "2024-06-30"}
    assert isinstance(result["model_id"], str) and result["model_id"].startswith("model-")
    # parameters 应是个 dict
    assert isinstance(result["parameters"], dict) and result["parameters"]


def test_generate_model_spec_is_deterministic_for_same_metadata():
    metadata = {
        "ticker": "MSFT",
        "factor_name": "value_composite",
        "factor_type": "risk",
        "date_range": {"start": "2020-01-01", "end": "2024-12-31"},
    }
    a = registry.call("generate_model_spec", {"metadata": metadata})
    b = registry.call("generate_model_spec", {"metadata": metadata})
    assert a["model_id"] == b["model_id"]


def test_generate_model_spec_requires_metadata():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("generate_model_spec", {})


# ---------------------------------------------------------------------------
# write_blackboard（含 dedupe）— Day 3 评审后改造：调真 BlackboardService
# ---------------------------------------------------------------------------


def test_write_blackboard_creates_project_and_group_entries(tmp_path, monkeypatch):
    """Day 3 评审修复（leader 指令 2）：write_blackboard 改写为调 BlackboardService，
    写入 PROJECT（跨组共享）+ GROUP（owner private）双 scope。
    """
    db_path = tmp_path / "blackboard.sqlite"
    from tools.model import write_blackboard as wb_module

    # 强制 raw execute 跑（绕开 dedupe 缓存），并把 db_path 注入 ctx
    raw_execute = wb_module.write_blackboard_execute
    args = wb_module.WriteBlackboardArgs(key="model_spec_1", value={"model_id": "m1"})
    ctx = {
        "thread_id": "model-agent-1700000000",
        "group": "model",
        "blackboard_db_path": str(db_path),
    }
    result = raw_execute(args, ctx)

    # 双 scope 都有 entry
    assert "project_entry" in result
    assert "group_entry" in result
    assert result["project_entry"]["scope"] == "project"
    assert result["project_entry"]["key"] == "shared.model_entries.model_spec_1"
    assert result["project_entry"]["value"] == {"model_id": "m1"}

    assert result["group_entry"]["scope"] == "group"
    assert result["group_entry"]["key"] == "model_spec_1"
    assert result["group_entry"]["value"] == {"model_id": "m1"}
    assert result["group_entry"]["group"] == "model"

    # 都是 v=1 (新写)
    assert result["project_entry"]["version"] == 1
    assert result["group_entry"]["version"] == 1


def test_write_blackboard_increments_version_on_overwrite(tmp_path):
    """同一 key 第二次写入，version 应递增（BlackboardService 自动语义）。"""
    db_path = tmp_path / "blackboard.sqlite"
    from tools.model import write_blackboard as wb_module

    raw_execute = wb_module.write_blackboard_execute
    ctx = {
        "thread_id": "model-agent-1700000001",
        "group": "model",
        "blackboard_db_path": str(db_path),
    }

    # 第一次写
    first = raw_execute(
        wb_module.WriteBlackboardArgs(key="same", value={"v": 1}), ctx=ctx
    )
    # 第二次写同一 key
    second = raw_execute(
        wb_module.WriteBlackboardArgs(key="same", value={"v": 2}), ctx=ctx
    )

    assert first["group_entry"]["version"] == 1
    assert second["group_entry"]["version"] == 2
    assert second["group_entry"]["value"] == {"v": 2}


def test_write_blackboard_dedupes_within_window(tmp_path):
    """同一 key 在 300 秒窗口内通过 wrapped_execute 重复调用，第二次走 dedupe 缓存。"""
    db_path = tmp_path / "dedupe.sqlite"
    from tools.model import write_blackboard as wb_module

    fresh = wb_module.dedupe_within(
        seconds=300,
        key=lambda args, ctx: f"{ctx.get('thread_id', 'default')}::{args.key}",
        db_path=db_path,
    )(wb_module.write_blackboard_execute)

    ctx = {"thread_id": "model-agent-1700000099", "group": "model"}
    first = fresh(wb_module.WriteBlackboardArgs(key="dup_key", value={"v": 1}), ctx=ctx)
    second = fresh(wb_module.WriteBlackboardArgs(key="dup_key", value={"v": 2}), ctx=ctx)

    # 第二次走 dedupe 缓存，返回与第一次完全一致
    assert first == second
    assert first["project_entry"]["value"] == {"v": 1}


def test_write_blackboard_requires_key():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("write_blackboard", {"value": {"x": 1}})


def test_synthesize_task_id_is_deterministic_and_distinct():
    """🟢P2-8：_synthesize_task_id 单测。

    验证：
    1. 稳定：相同 thread_id 两次调用返回相同 task_id
    2. 区分：不同 thread_id 返回不同 task_id
    3. 严格满足 TASK_ID_PATTERN (``^T\\d+(\\.\\d+){0,4}$``)
    """
    from tools.model.write_blackboard import _synthesize_task_id

    # 1. 稳定
    assert _synthesize_task_id("model-agent-1700000000") == _synthesize_task_id(
        "model-agent-1700000000"
    )

    # 2. 区分
    assert _synthesize_task_id("model-agent-1700000000") != _synthesize_task_id(
        "model-agent-1700000001"
    )

    # 3. 严格匹配 TASK_ID_PATTERN
    import re
    from schemas import TASK_ID_PATTERN

    samples = [
        "model-agent-1700000000",
        "risk-flow-abc12345",
        "factor-1700000099-xyz",
        "x",  # edge case: 极短输入
    ]
    for tid in samples:
        tid_out = _synthesize_task_id(tid)
        assert re.match(TASK_ID_PATTERN, tid_out), (
            f"{tid!r} -> {tid_out!r} 不满足 TASK_ID_PATTERN"
        )


def test_write_blackboard_via_registry_call_chain(monkeypatch, tmp_path):
    """Day 3 评审修复（审查报告 P1-6）：通过 ``registry.call`` 全链路调用 write_blackboard。

    之前的测试直接调 wb_module.write_blackboard_execute，绕过了：
    1. ToolDef schema 校验
    2. registry.call 自身的 ctx 注入路径
    3. production shipped write_blackboard_wrapped_execute（含 dedupe_within）

    本测试保证 tool 实际的 production 链路（registry → ToolDef.execute → wrapped_execute
    → BlackboardService.write_value → SQLite）能跑通，并验证 dedupe 缓存也实际生效。
    """
    db_path = tmp_path / "chain_blackboard.sqlite"
    dedupe_db = tmp_path / "chain_dedupe.sqlite"

    # 把 blackboard db 路径注入 ctx
    monkeypatch.setattr(
        "tools.model.write_blackboard.write_blackboard_execute",
        __import__("tools.model.write_blackboard", fromlist=["write_blackboard_execute"]).write_blackboard_execute,
    )
    # 重绑 dedupe DB（写到 tmp_path，避免污染 repo）
    from tools.model import write_blackboard as wb_module
    import tools.utils.dedupe as dedupe_module

    original_factory = dedupe_module.dedupe_within

    def _isolated_dedupe(seconds, key, **kwargs):
        kwargs.setdefault("db_path", dedupe_db)
        return original_factory(seconds, key, **kwargs)

    monkeypatch.setattr(wb_module, "dedupe_within", _isolated_dedupe)

    ctx = {
        "thread_id": "model-agent-1700111111",
        "group": "model",
        "blackboard_db_path": str(db_path),
    }

    # 1. 第一次调用：走全链路 registry.call
    result1 = registry.call(
        "write_blackboard",
        {"key": "chain_test_key", "value": {"v": "first"}},
        ctx=ctx,
    )
    assert "project_entry" in result1
    assert "group_entry" in result1
    assert result1["group_entry"]["value"] == {"v": "first"}
    assert result1["group_entry"]["version"] == 1

    # 2. 第二次调用同 key（在 dedupe 窗口内）—— 应走 wrapped_execute 缓存
    #    返回 *cached* 上一次结果（value 不变）
    result2 = registry.call(
        "write_blackboard",
        {"key": "chain_test_key", "value": {"v": "second"}},
        ctx=ctx,
    )
    assert result2["group_entry"]["value"] == {"v": "first"}, (
        "dedupe_within 在 300s 窗口内应短路，第二次 value 不该更新到 v=second"
    )
    # 同时验证 SQLite 中 GROUP entry 没被改 — version 应仍为 1
    assert result2["group_entry"]["version"] == 1

    # 3. schema 校验：缺 key 应被 registry 转成 ValueError
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("write_blackboard", {"value": {"x": 1}}, ctx=ctx)


# ---------------------------------------------------------------------------
# trigger_risk_flow（含 dedupe）
# ---------------------------------------------------------------------------


def test_trigger_risk_flow_returns_flow_id_format():
    raw_execute = trigger_risk_flow_tool.execute
    trigger_risk_flow_tool.execute = raw_execute.__wrapped__
    try:
        result = registry.call(
            "trigger_risk_flow", {"blackboard_key": "model_spec_1"}
        )
    finally:
        trigger_risk_flow_tool.execute = raw_execute

    assert re.fullmatch(r"risk-flow-[0-9a-f]{8}", result["flow_id"])
    assert isinstance(result["triggered_at"], str)


def test_trigger_risk_flow_dedupes_within_window(tmp_path):
    """同一 blackboard_key 在 600 秒窗口内多次触发应返回同一 flow_id。"""
    from tools.model import trigger_risk_flow as rf_module

    db_path = tmp_path / "dedupe.sqlite"
    fresh = rf_module.dedupe_within(
        seconds=600,
        key=lambda args, ctx: f"{args.blackboard_key}",
        db_path=db_path,
    )(rf_module.trigger_risk_flow_execute)

    a = fresh(
        rf_module.TriggerRiskFlowArgs(blackboard_key="same_key"), ctx={}
    )
    b = fresh(
        rf_module.TriggerRiskFlowArgs(blackboard_key="same_key"), ctx={}
    )
    assert a == b
    assert re.fullmatch(r"risk-flow-[0-9a-f]{8}", a["flow_id"])


def test_trigger_risk_flow_requires_blackboard_key():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("trigger_risk_flow", {})