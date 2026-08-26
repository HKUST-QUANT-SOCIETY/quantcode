"""Tests for the model group's 5 ToolDef tools — Day 3 尹一帆。

覆盖：
- import 副作用 ``tools.model._register`` 把 5 个 tool 全部注册进全局 registry
- 每个 tool 通过 ``registry.call(tool_id, args)`` 能正常执行并返回约定结构
- schema 校验：缺字段 / 类型错会被 registry 转成 ``ValueError``
- dedupe 副作用：``write_blackboard`` / ``trigger_risk_flow`` 在窗口内
  对同一 key 返回缓存结果
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.blackboard import BlackboardService, DEFAULT_SESSION_ID
from schemas import BlackboardScope, GroupName, WritePolicy
from tools.registry import registry

# 让 ``tools.model._register`` 的 import 副作用把所有 5 个 tool 注册进去
import tools.model._register as model_register
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

VALID_SESSION = "S0123456789abcdef"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PR = FIXTURES_DIR / "sample_model_pr" / "README.md"
SAMPLE_MODEL_SPEC = FIXTURES_DIR / "sample_model" / "model_spec.json"


def _sample_model_spec() -> dict:
    return json.loads(SAMPLE_MODEL_SPEC.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _ensure_model_tools_registered():
    """确保 5 个 model tool 已注册，防止被其他 test 的 clean_registry 清掉。

    其他测试文件用 ``registry._tools.clear()`` 清空，模块级 import 只跑一次，
    所以需要每次 test 前显式 reload 一次。
    """
    import importlib

    importlib.reload(model_register)
    yield


# ---------------------------------------------------------------------------
# 注册相关
# ---------------------------------------------------------------------------


def test_model_tools_all_registered():
    """import 副作用应把全部 5 个 model tool 注册进 registry。"""
    assert EXPECTED_TOOL_IDS.issubset(set(registry.list_ids()))


def test_each_tool_def_has_required_fields():
    """每个 tool 的 ToolDef 应当填充 id/description/schema/execute。"""
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


def test_read_pr_reads_model_pr_fixture():
    result = registry.call("read_pr", {"pr_path": str(SAMPLE_PR)})
    assert result["source"] == str(SAMPLE_PR)
    assert "## ModelSpec" in result["body"]
    assert result["pr_url"] is None


def test_read_pr_fetches_github_pr(monkeypatch):
    from tools.model import read_pr as read_pr_module

    model_spec = _sample_model_spec()
    model_spec.pop("commit_sha")
    body = "## ModelSpec\n\n```json\n" + json.dumps(model_spec, indent=2) + "\n```"
    head_sha = "abcdef1234567890abcdef1234567890abcdef12"
    calls = []

    def fake_github_request(method, repo, path, token, payload=None):
        calls.append((method, repo, path, token, payload))
        assert method == "GET"
        assert repo == "HKUST-QUANT-SOCIETY/opencode"
        assert token == "test-token"
        if path == "/pulls/7":
            return {
                "html_url": "https://github.com/HKUST-QUANT-SOCIETY/opencode/pull/7",
                "title": "Add pb roe ranker",
                "body": body,
                "head": {"sha": head_sha},
                "base": {"sha": "1234567890abcdef1234567890abcdef12345678"},
                "user": {"login": "chen-zhenhong"},
            }
        if path == "/pulls/7/files?per_page=100":
            return [
                {
                    "filename": "models/pb_roe_ranker.py",
                    "status": "modified",
                    "additions": 12,
                    "deletions": 2,
                    "changes": 14,
                    "patch": "@@ -1,2 +1,4 @@\n+MODEL_SPEC = {...}",
                }
            ]
        raise AssertionError(f"unexpected GitHub path: {path}")

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "HKUST-QUANT-SOCIETY/opencode")
    monkeypatch.setattr(read_pr_module, "github_request", fake_github_request)

    result = registry.call("read_pr", {"pr_number": 7})

    assert result["source"] == "github:HKUST-QUANT-SOCIETY/opencode#7"
    assert result["pr_number"] == 7
    assert result["pr_url"] == "https://github.com/HKUST-QUANT-SOCIETY/opencode/pull/7"
    assert result["head_sha"] == head_sha
    assert result["author"] == "chen-zhenhong"
    assert "models/pb_roe_ranker.py" in result["diff"]
    assert result["files"][0]["additions"] == 12
    assert [call[2] for call in calls] == [
        "/pulls/7",
        "/pulls/7/files?per_page=100",
    ]

    metadata = registry.call("extract_metadata", {"pr": result})
    assert metadata["pr_url"] == result["pr_url"]
    assert metadata["commit_sha"] == head_sha
    model_spec = registry.call("generate_model_spec", {"metadata": metadata})
    assert model_spec["model_name"] == "pb_roe_ranker"
    assert model_spec["commit_sha"] == head_sha


def test_read_pr_validates_pr_path_type():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("read_pr", {"pr_path": 123})


def test_read_pr_requires_source():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("read_pr", {})


# ---------------------------------------------------------------------------
# extract_metadata
# ---------------------------------------------------------------------------


def test_extract_metadata_reads_model_spec_json_from_fixture():
    pr = registry.call("read_pr", {"pr_path": str(SAMPLE_PR)})
    result = registry.call("extract_metadata", {"pr": pr})
    assert result["model_name"] == "pb_roe_ranker"
    assert result["model_type"] == "boosting"
    assert result["commit_sha"] == "abcdef1"
    assert result["risk_metadata"]["universe"] == "CSI1000"


def test_extract_metadata_requires_source():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("extract_metadata", {})


# ---------------------------------------------------------------------------
# generate_model_spec
# ---------------------------------------------------------------------------


def test_generate_model_spec_validates_day1_schema():
    pr = registry.call("read_pr", {"pr_path": str(SAMPLE_PR)})
    metadata = registry.call("extract_metadata", {"pr": pr})
    result = registry.call("generate_model_spec", {"metadata": metadata})
    assert result["model_name"] == "pb_roe_ranker"
    assert result["model_type"] == "boosting"
    assert result["training_data_start"] == "2021-01-01"
    assert result["training_data_end"] == "2023-12-31"
    assert result["as_of_date"] == "2024-03-15"


def test_generate_model_spec_rejects_invalid_schema():
    with pytest.raises(Exception, match="training_data_start"):
        registry.call("generate_model_spec", {"metadata": {"model_name": "missing_fields"}})


def test_generate_model_spec_requires_metadata():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("generate_model_spec", {})


# ---------------------------------------------------------------------------
# write_blackboard（含 dedupe）— Day 3 评审后改造：调真 BlackboardService
# ---------------------------------------------------------------------------


def test_write_blackboard_creates_project_entry(tmp_path):
    """write_blackboard 写入 PROJECT scope，供 risk 组跨组读取。"""
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
    assert "project_entry" in result
    assert result["project_entry"]["scope"] == "project"
    assert result["project_entry"]["key"] == "shared.model_entries.model_spec_1"
    assert result["project_entry"]["value"] == {"model_id": "m1"}
    assert result["project_entry"]["version"] == 1

    risk_board = BlackboardService(
        db_path,
        session_id="model-agent-1700000000",
        requester_group=GroupName.RISK,
    )
    assert risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.model_entries.model_spec_1",
    ) is not None


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

    assert first["project_entry"]["version"] == 1
    assert second["project_entry"]["version"] == 2
    assert second["project_entry"]["value"] == {"v": 2}


def test_write_blackboard_dedupes_within_window(tmp_path):
    """同一 key 在 300 秒窗口内通过 wrapped_execute 重复调用，第二次走 dedupe 缓存。"""
    db_path = tmp_path / "dedupe.sqlite"
    from tools.model import write_blackboard as wb_module

    fresh = wb_module.dedupe_within(
        seconds=300,
        key=lambda args, ctx: f"{ctx.get('thread_id', 'default')}::{args.key}",
        db_path=db_path,
    )(wb_module.write_blackboard_execute)

    ctx = {
        "thread_id": "model-agent-1700000099",
        "group": "model",
        "blackboard_db_path": str(tmp_path / "blackboard.sqlite"),
    }
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

    from tools.model import write_blackboard as wb_module

    fresh_execute = wb_module.dedupe_within(
        seconds=300,
        key=lambda args, ctx: f"{ctx.get('thread_id', 'default')}::{args.key}",
        db_path=dedupe_db,
    )(wb_module.write_blackboard_execute)
    monkeypatch.setattr(wb_module.write_blackboard_tool, "execute", fresh_execute)

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
    assert "group_entry" not in result1
    assert result1["project_entry"]["value"] == {"v": "first"}
    assert result1["project_entry"]["version"] == 1

    # 2. 第二次调用同 key（在 dedupe 窗口内）—— 应走 wrapped_execute 缓存
    #    返回 *cached* 上一次结果（value 不变）
    result2 = registry.call(
        "write_blackboard",
        {"key": "chain_test_key", "value": {"v": "second"}},
        ctx=ctx,
    )
    assert result2["project_entry"]["value"] == {"v": "first"}, (
        "dedupe_within 在 300s 窗口内应短路，第二次 value 不该更新到 v=second"
    )
    assert result2["project_entry"]["version"] == 1

    # 3. schema 校验：缺 key 应被 registry 转成 ValueError
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("write_blackboard", {"value": {"x": 1}}, ctx=ctx)


# ---------------------------------------------------------------------------
# trigger_risk_flow（含 dedupe）
# ---------------------------------------------------------------------------


def test_trigger_risk_flow_writes_project_queue(tmp_path):
    db_path = tmp_path / "risk_queue.sqlite"
    from tools.model import write_blackboard as wb_module

    wb_module.write_blackboard_execute(
        wb_module.WriteBlackboardArgs(
            key="model_spec_1",
            value={
                "model_name": "pb_roe_ranker",
                "commit_sha": "abcdef1",
                "pr_url": None,
                "api_key": "must-not-cross-groups",
            },
        ),
        ctx={
            "thread_id": VALID_SESSION,
            "group": "model",
            "blackboard_db_path": str(db_path),
        },
    )

    raw_execute = trigger_risk_flow_tool.execute
    trigger_risk_flow_tool.execute = raw_execute.__wrapped__
    try:
        result = registry.call(
            "trigger_risk_flow",
            {"blackboard_key": "shared.model_entries.model_spec_1"},
            ctx={
                "thread_id": VALID_SESSION,
                "group": "model",
                "blackboard_db_path": str(db_path),
            },
        )
    finally:
        trigger_risk_flow_tool.execute = raw_execute

    assert result["risk_queue_key"] == "shared.pending_risk_reviews"
    assert result["review_id"] == "abcdef1"
    assert result["review"]["to_group"] == "risk"

    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    queue = risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.pending_risk_reviews",
    )
    assert queue is not None
    assert "abcdef1" in queue.value["reviews"]

    shared_risk_board = BlackboardService(
        db_path,
        session_id=DEFAULT_SESSION_ID,
        requester_group=GroupName.RISK,
    )
    shared_queue = shared_risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.pending_risk_reviews",
    )
    assert shared_queue is not None
    shared_review = shared_queue.value["reviews"]["abcdef1"]
    assert shared_review["context_snapshot"]["api_key"] == "[redacted]"


def test_trigger_risk_flow_dedupes_within_window(tmp_path):
    """同一 blackboard_key 在 600 秒窗口内多次触发应返回同一 queue 写入结果。"""
    from tools.model import trigger_risk_flow as rf_module

    db_path = tmp_path / "dedupe.sqlite"
    fresh = rf_module.dedupe_within(
        seconds=600,
        key=lambda args, ctx: f"{args.blackboard_key}",
        db_path=db_path,
    )(rf_module.trigger_risk_flow_execute)

    ctx = {
        "thread_id": VALID_SESSION,
        "group": "model",
        "blackboard_db_path": str(tmp_path / "blackboard.sqlite"),
    }
    a = fresh(
        rf_module.TriggerRiskFlowArgs(blackboard_key="same_key"), ctx=ctx
    )
    b = fresh(
        rf_module.TriggerRiskFlowArgs(blackboard_key="same_key"), ctx=ctx
    )
    assert a == b
    assert a["risk_queue_key"] == "shared.pending_risk_reviews"


def test_trigger_risk_flow_requires_blackboard_key():
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.call("trigger_risk_flow", {})


# ---------------------------------------------------------------------------
# model → risk cross-group flow
# ---------------------------------------------------------------------------


def test_blackboard_project_scope_visible_and_group_scope_hidden(tmp_path):
    db_path = tmp_path / "permission.sqlite"
    model_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    model_spec = _sample_model_spec()
    model_board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.model_entries.visible_spec",
        value=model_spec,
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T1.1",
        written_by_group=GroupName.MODEL,
    )
    model_board.write_value(
        scope=BlackboardScope.GROUP,
        key="private_spec",
        value=model_spec,
        group=GroupName.MODEL,
        written_by_task_id="T1.2",
        written_by_group=GroupName.MODEL,
    )

    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    assert risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.model_entries.visible_spec",
    ) is not None
    assert risk_board.get_entry(
        BlackboardScope.GROUP,
        GroupName.MODEL,
        "private_spec",
    ) is None


def test_model_to_risk_cross_group_flow_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    import tools.risk._register  # noqa: F401
    from runner.compose_executor import execute_compose_flow, unregister_flow
    from runner.langgraph_base import clear_checkpointer_cache
    from runner.risk_agent import register_risk_gate_flow
    from tools.model import trigger_risk_flow as rf_module
    from tools.model import write_blackboard as wb_module
    from tools.risk.risk_tools import clear_write_pr_comment_dedupe_cache

    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "model_to_risk.sqlite"
    pr = registry.call("read_pr", {"pr_path": str(SAMPLE_PR)})
    metadata = registry.call("extract_metadata", {"pr": pr})
    metadata["pr_url"] = "https://github.com/HKUST-QUANT-SOCIETY/opencode/pull/7"
    model_spec = registry.call("generate_model_spec", {"metadata": metadata})
    ctx = {
        "thread_id": VALID_SESSION,
        "group": "model",
        "blackboard_db_path": str(db_path),
    }
    write_result = wb_module.write_blackboard_execute(
        wb_module.WriteBlackboardArgs(key="model_spec_7", value=model_spec),
        ctx=ctx,
    )
    blackboard_key = write_result["project_entry"]["key"]

    trigger_result = rf_module.trigger_risk_flow_execute(
        rf_module.TriggerRiskFlowArgs(blackboard_key=blackboard_key),
        ctx=ctx,
    )
    assert trigger_result["review"]["status"] == "pending"
    assert trigger_result["review"]["to_group"] == "risk"
    assert trigger_result["review"]["blackboard_key"] == blackboard_key

    try:
        register_risk_gate_flow(checkpoint_db=tmp_path / "checkpoints.db")
        result = execute_compose_flow(
            group="risk",
            flow_name="risk:gate",
            input_data={
                "scenario": "normal",
                "project_id": VALID_SESSION,
                "blackboard_db_path": str(db_path),
                "blackboard_key": blackboard_key,
                "pr_number": "7",
                "head_sha": model_spec["commit_sha"],
                "pr_url": model_spec["pr_url"],
                "dedupe_db_path": str(tmp_path / "dedupe.sqlite"),
                "artifacts_root": str(tmp_path / "pr-comments"),
            },
            thread_id="risk-model-to-risk-test",
        )
    finally:
        unregister_flow("risk", "risk:gate")
        clear_checkpointer_cache()
        clear_write_pr_comment_dedupe_cache()

    assert result["output_data"]["status"] == "completed"
    assert result["output_data"]["risk_profile"]["strategy_id"] == "pb_roe_ranker"
    assert result["output_data"]["pr_comment"] is not None
    assert result["output_data"]["acceptance"]["verdict"] == "pass"
