"""Tests for ComposeTask + BlackboardState (Pattern 1 + 2 contracts)."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from schemas import (
    BlackboardEntry,
    BlackboardScope,
    BlackboardState,
    ComposeTask,
    ComposeTaskEvent,
    GroupName,
    TaskEventKind,
    TaskOutcome,
    TaskStatus,
    WritePolicy,
)


# ---------------------------------------------------------------------------
# Mock payload types for testing Generic[TIn, TOut]
# ---------------------------------------------------------------------------

class MockFactorSpec(BaseModel):
    name: str
    universe: str = "CSI1000"


class MockFactorReport(BaseModel):
    ic_mean: float
    ir: float


VALID_SESSION = "S0123456789abcdef"  # 16 hex chars


def _make_root_task(**overrides) -> ComposeTask[MockFactorSpec, MockFactorReport]:
    defaults = dict(
        task_id="T1",
        session_id=VALID_SESSION,
        root_task_id="T1",
        group=GroupName.FACTOR,
        summary="test factor eval",
        input=MockFactorSpec(name="pb_roe"),
    )
    defaults.update(overrides)
    return ComposeTask[MockFactorSpec, MockFactorReport](**defaults)


# ---------------------------------------------------------------------------
# ComposeTask identity & tree
# ---------------------------------------------------------------------------

def test_root_task_valid():
    task = _make_root_task()
    assert task.task_id == "T1"
    assert task.depth == 0
    assert task.parent_task_id is None


def test_child_task_valid():
    task = _make_root_task(
        task_id="T1.2",
        parent_task_id="T1",
        depth=1,
    )
    assert task.task_id == "T1.2"
    assert task.depth == 1


def test_root_task_id_prefix_enforced():
    with pytest.raises(ValidationError, match="not a prefix"):
        _make_root_task(task_id="T2.1", root_task_id="T1", parent_task_id="T1", depth=1)


def test_root_task_cannot_have_parent():
    with pytest.raises(ValidationError, match="root task"):
        _make_root_task(parent_task_id="T1")


def test_task_id_pattern():
    with pytest.raises(ValidationError):
        _make_root_task(task_id="not-a-task-id")


def test_max_depth_enforced():
    with pytest.raises(ValidationError):
        _make_root_task(
            task_id="T1.2.3.4.5.6",
            root_task_id="T1",
            parent_task_id="T1.2.3.4.5",
            depth=5,  # exceeds MAX_TREE_DEPTH=4
        )


# ---------------------------------------------------------------------------
# ComposeTask status/outcome invariants
# ---------------------------------------------------------------------------

def test_open_task_no_outcome():
    task = _make_root_task(status=TaskStatus.OPEN)
    assert task.outcome is None


def test_done_requires_success():
    with pytest.raises(ValidationError, match="DONE requires outcome=SUCCESS"):
        _make_root_task(status=TaskStatus.DONE, outcome=TaskOutcome.FAILURE)


def test_done_success_valid():
    task = _make_root_task(
        status=TaskStatus.DONE,
        outcome=TaskOutcome.SUCCESS,
        output=MockFactorReport(ic_mean=0.05, ir=0.7),
    )
    assert task.outcome == TaskOutcome.SUCCESS


def test_abandoned_requires_failure_family():
    with pytest.raises(ValidationError, match="ABANDONED requires"):
        _make_root_task(status=TaskStatus.ABANDONED, outcome=TaskOutcome.SUCCESS)


def test_abandoned_rejected_valid():
    """HumanGate 拒绝 = ABANDONED + REJECTED"""
    task = _make_root_task(status=TaskStatus.ABANDONED, outcome=TaskOutcome.REJECTED)
    assert task.outcome == TaskOutcome.REJECTED


def test_non_terminal_cannot_have_outcome():
    with pytest.raises(ValidationError, match="terminal statuses"):
        _make_root_task(status=TaskStatus.IN_PROGRESS, outcome=TaskOutcome.SUCCESS)


# ---------------------------------------------------------------------------
# Generic[TIn, TOut] typing works
# ---------------------------------------------------------------------------

def test_generic_typing_flows():
    task = _make_root_task()
    assert isinstance(task.input, MockFactorSpec)
    assert task.input.name == "pb_roe"


def test_json_serialization_uses_epoch():
    task = _make_root_task()
    data = task.model_dump(mode="json")
    assert isinstance(data["created_at"], int)


# ---------------------------------------------------------------------------
# BlackboardEntry scope constraints
# ---------------------------------------------------------------------------

def test_group_scope_requires_group():
    with pytest.raises(ValidationError, match="scope=GROUP requires"):
        BlackboardEntry(
            key="ic_registry",
            scope=BlackboardScope.GROUP,
            group=None,
            value={"count": 3},
            written_by_task_id="T1",
            written_by_group=GroupName.FACTOR,
        )


def test_group_scope_valid():
    entry = BlackboardEntry(
        key="ic_registry",
        scope=BlackboardScope.GROUP,
        group=GroupName.FACTOR,
        value={"count": 3},
        written_by_task_id="T1",
        written_by_group=GroupName.FACTOR,
    )
    assert entry.group == GroupName.FACTOR


def test_group_append_only_group_or_project():
    with pytest.raises(ValidationError, match="GROUP_APPEND"):
        BlackboardEntry(
            key="log",
            scope=BlackboardScope.SESSION,
            write_policy=WritePolicy.GROUP_APPEND,
            value=[],
            written_by_task_id="T1",
            written_by_group=GroupName.FACTOR,
        )


# ---------------------------------------------------------------------------
# BlackboardState composite key
# ---------------------------------------------------------------------------

def test_make_entry_key_project():
    key = BlackboardState.make_entry_key(BlackboardScope.PROJECT, None, "last_pr")
    assert key == "project:_:last_pr"


def test_make_entry_key_group():
    key = BlackboardState.make_entry_key(BlackboardScope.GROUP, GroupName.FACTOR, "ic")
    assert key == "group:factor:ic"


def test_blackboard_add_get_remove():
    bb = BlackboardState(session_id=VALID_SESSION)
    entry = BlackboardEntry(
        key="ic_registry",
        scope=BlackboardScope.GROUP,
        group=GroupName.FACTOR,
        value={"count": 3},
        written_by_task_id="T1",
        written_by_group=GroupName.FACTOR,
    )
    bb.add_entry(entry)

    retrieved = bb.get_entry(BlackboardScope.GROUP, GroupName.FACTOR, "ic_registry")
    assert retrieved is not None
    assert retrieved.value == {"count": 3}

    # Cross-group read must return None (hard walls)
    assert bb.get_entry(BlackboardScope.GROUP, GroupName.RISK, "ic_registry") is None

    assert bb.remove_entry(BlackboardScope.GROUP, GroupName.FACTOR, "ic_registry") is True
    assert bb.remove_entry(BlackboardScope.GROUP, GroupName.FACTOR, "ic_registry") is False


# ---------------------------------------------------------------------------
# ComposeTaskEvent HANDOFF constraint
# ---------------------------------------------------------------------------

def test_handoff_requires_from_to_group():
    with pytest.raises(ValidationError, match="HANDOFF"):
        ComposeTaskEvent(
            event_id=1,
            task_id="T1",
            session_id=VALID_SESSION,
            kind=TaskEventKind.HANDOFF,
        )


def test_handoff_valid():
    ev = ComposeTaskEvent(
        event_id=1,
        task_id="T1",
        session_id=VALID_SESSION,
        kind=TaskEventKind.HANDOFF,
        from_group=GroupName.MODEL,
        to_group=GroupName.RISK,
    )
    assert ev.from_group == GroupName.MODEL


# ---------------------------------------------------------------------------
# JSON Schema export (for cross-language / CI use)
# ---------------------------------------------------------------------------

def test_json_schema_export_compose_task():
    """Can export JSON Schema from Pydantic (PRD §6.3 requirement)."""
    schema = ComposeTask[MockFactorSpec, MockFactorReport].model_json_schema()
    assert "properties" in schema
    assert "task_id" in schema["properties"]


def test_json_schema_export_blackboard_state():
    schema = BlackboardState.model_json_schema()
    assert "properties" in schema
    assert "entries" in schema["properties"]
