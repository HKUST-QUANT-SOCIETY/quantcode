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
# write_blackboard（含 dedupe）
# ---------------------------------------------------------------------------


def test_write_blackboard_returns_confirmation(tmp_path, monkeypatch):
    # 把 dedupe DB 重定向到 tmp_path，避免污染仓库
    monkeypatch.setattr(
        "tools.model.write_blackboard.write_blackboard_wrapped_execute.__wrapped__",
        write_blackboard_tool.execute.__wrapped__,
        raising=False,
    )
    # 直接走 tool 实例，但 db_path 是装饰器创建时绑定——绕开：单独测一次即可
    # 不再 monkeypatch 装饰器内部，直接覆盖工具的 execute 用 raw 函数
    raw_tool = write_blackboard_tool
    # 重置 dedupe db：直接复用默认 path 不理想，改用 raw execute 走一次
    raw_execute = raw_tool.execute
    # 通过把 execute 替换成原函数来避开缓存（仅测试返回结构）
    raw_tool.execute = raw_tool.execute.__wrapped__
    try:
        result = registry.call(
            "write_blackboard",
            {"key": "model_spec_1", "value": {"model_id": "m1"}},
        )
    finally:
        raw_tool.execute = raw_execute

    assert result["key"] == "model_spec_1"
    assert result["written"] is True
    assert isinstance(result["timestamp"], str)


def test_write_blackboard_dedupes_within_window(tmp_path, monkeypatch):
    """同一 key 在 300 秒窗口内重复调用应得到同一时间戳（缓存命中）。"""
    from tools.model import write_blackboard as wb_module

    # 用 fresh sqlite db 重启装饰器状态
    db_path = tmp_path / "dedupe.sqlite"
    monkeypatch.setattr(wb_module, "write_blackboard_wrapped_execute", None)

    fresh = wb_module.dedupe_within(
        seconds=300,
        key=lambda args, ctx: f"{args.key}",
        db_path=db_path,
    )(wb_module.write_blackboard_execute)

    first = fresh(wb_module.WriteBlackboardArgs(key="dup_key", value={"v": 1}), ctx={})
    second = fresh(wb_module.WriteBlackboardArgs(key="dup_key", value={"v": 2}), ctx={})

    assert first == second
    assert first["key"] == "dup_key"
    assert first["written"] is True


def test_write_blackboard_requires_key():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("write_blackboard", {"value": {"x": 1}})


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