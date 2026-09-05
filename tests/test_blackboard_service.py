"""Tests for the persistent Blackboard service."""
from __future__ import annotations

import pytest

from runner.blackboard import BlackboardPermissionError, BlackboardService
from schemas import BlackboardScope, GroupName, WritePolicy

VALID_SESSION = "S0123456789abcdef"


def test_project_entries_are_cross_group_readable(tmp_path):
    db_path = tmp_path / "blackboard.db"
    model_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    model_board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.model_specs.pb_roe_ranker",
        value={"model_name": "pb_roe_ranker"},
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )

    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    entry = risk_board.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.model_specs.pb_roe_ranker",
    )

    assert entry is not None
    assert entry.value == {"model_name": "pb_roe_ranker"}


def test_group_entries_are_private_to_owner_group(tmp_path):
    db_path = tmp_path / "blackboard.db"
    model_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    model_board.write_value(
        scope=BlackboardScope.GROUP,
        group=GroupName.MODEL,
        key="model.private_specs.pb_roe_ranker",
        value={"secret": "model-only"},
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )

    assert model_board.get_entry(
        BlackboardScope.GROUP,
        GroupName.MODEL,
        "model.private_specs.pb_roe_ranker",
    ) is not None

    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    assert risk_board.get_entry(
        BlackboardScope.GROUP,
        GroupName.MODEL,
        "model.private_specs.pb_roe_ranker",
    ) is None
    assert risk_board.list_entries(scope=BlackboardScope.GROUP) == []


def test_cross_group_write_to_group_scope_is_rejected(tmp_path):
    board = BlackboardService(
        tmp_path / "blackboard.db",
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )

    with pytest.raises(BlackboardPermissionError):
        board.write_value(
            scope=BlackboardScope.GROUP,
            group=GroupName.MODEL,
            key="model.private_specs.pb_roe_ranker",
            value={"secret": "nope"},
            written_by_task_id="T1",
            written_by_group=GroupName.RISK,
        )


def test_bound_group_cannot_be_overridden_by_per_call_requester(tmp_path):
    """A service-bound identity must apply to every operation."""
    board = BlackboardService(
        tmp_path / "blackboard.db",
        session_id=VALID_SESSION,
        requester_group=GroupName.FACTOR,
    )

    with pytest.raises(BlackboardPermissionError, match="cannot override"):
        board.write_value(
            scope=BlackboardScope.GROUP,
            group=GroupName.RISK,
            key="risk.private",
            value={"secret": True},
            written_by_task_id="T1",
            written_by_group=GroupName.RISK,
            requester_group=GroupName.RISK,
        )

    with pytest.raises(BlackboardPermissionError, match="cannot override"):
        board.get_entry(
            BlackboardScope.GROUP,
            GroupName.RISK,
            "risk.private",
            requester_group=GroupName.RISK,
        )


def test_blackboard_persists_across_service_instances(tmp_path):
    db_path = tmp_path / "blackboard.db"
    first = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    first.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.pending_risk_reviews",
        value={"reviews": {"abc": {"status": "pending"}}},
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )

    second = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    entry = second.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.pending_risk_reviews",
    )

    assert entry is not None
    assert entry.value["reviews"]["abc"]["status"] == "pending"


def test_overwrite_increments_version(tmp_path):
    board = BlackboardService(
        tmp_path / "blackboard.db",
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    first = board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.counter",
        value={"n": 1},
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )
    second = board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.counter",
        value={"n": 2},
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )

    assert first.version == 1
    assert second.version == 2
    assert second.value == {"n": 2}


# ---------------------------------------------------------------------------
# P0-2：write_policy 实装（OWNER / APPEND / GROUP_APPEND）
# ---------------------------------------------------------------------------


def test_owner_policy_rejects_overwrite_by_other_task(tmp_path):
    """OWNER（默认）：非原 task 不得覆盖。"""
    board = BlackboardService(
        tmp_path / "blackboard.db",
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.owner_key",
        value={"v": 1},
        written_by_task_id="T1",  # 默认 write_policy=OWNER
        written_by_group=GroupName.MODEL,
    )

    with pytest.raises(BlackboardPermissionError):
        board.write_value(
            scope=BlackboardScope.PROJECT,
            key="shared.owner_key",
            value={"v": 2},
            written_by_task_id="T2",
            written_by_group=GroupName.MODEL,
        )


def test_owner_policy_allows_overwrite_by_same_task(tmp_path):
    """OWNER：原 task 可覆盖（整体替换，version 递增）。"""
    board = BlackboardService(
        tmp_path / "blackboard.db",
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.owner_key",
        value={"v": 1},
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )
    updated = board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.owner_key",
        value={"v": 2},
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )

    assert updated.version == 2
    assert updated.value == {"v": 2}


def test_append_policy_appends_value_from_any_task(tmp_path):
    """APPEND：任何 task 仅可追加——新值 append 进已存 list。"""
    board = BlackboardService(
        tmp_path / "blackboard.db",
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.append_log",
        value=["a"],
        write_policy=WritePolicy.APPEND,
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )
    appended = board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.append_log",
        value="b",
        write_policy=WritePolicy.APPEND,
        written_by_task_id="T2",  # 不同 task
        written_by_group=GroupName.MODEL,
    )

    assert appended.value == ["a", "b"]
    assert appended.version == 2


def test_group_append_policy_allows_cross_group_append(tmp_path):
    """GROUP_APPEND：任何组可追加（跨组追加，P0-2 此前被实现成仅最后写者组可写）。"""
    db_path = tmp_path / "blackboard.db"
    model_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    model_board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.cross_group",
        value=["from-model"],
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )

    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    appended = risk_board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.cross_group",
        value="from-risk",
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T2",
        written_by_group=GroupName.RISK,
    )

    assert appended.value == ["from-model", "from-risk"]
    assert appended.version == 2


def test_group_append_non_list_payload_replaces_for_caller_merge(tmp_path):
    """GROUP_APPEND：已存 value 非 list（如 dict 载荷）时整体替换——
    dict 合并由调用方（trigger_risk_flow）自行 merge 后写入。"""
    db_path = tmp_path / "blackboard.db"
    model_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.MODEL,
    )
    model_board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.queue",
        value={"reviews": {"r1": {}}},
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T1",
        written_by_group=GroupName.MODEL,
    )
    risk_board = BlackboardService(
        db_path,
        session_id=VALID_SESSION,
        requester_group=GroupName.RISK,
    )
    merged = risk_board.write_value(
        scope=BlackboardScope.PROJECT,
        key="shared.queue",
        value={"reviews": {"r1": {}, "r2": {}}},
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id="T2",
        written_by_group=GroupName.RISK,
    )

    assert merged.value == {"reviews": {"r1": {}, "r2": {}}}
    assert merged.version == 2
