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

