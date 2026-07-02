"""
QuantCode Compose Task Schema v1 — Final Revision
==================================================

Alignment with MimoCode:
- Hierarchical task_id (T1.2.3) + internal_id (UUID) for stable references
- 5-state machine (open/in_progress/blocked/done/abandoned)
- outcome field for terminal states (success/failure/cancelled/rejected)
- datetime in Python, Unix epoch in JSON
- ComposeTaskEvent for audit trail
- GLOBAL blackboard scope

QuantCode-specific:
- Generic typing ComposeTask[TIn, TOut] for type-safe dispatching
- 6-group isolation with HARD walls (no cross-group reads by default)
- HANDOFF event kind for cross-group transitions
- GROUP_APPEND policy for collaborative writes
- dispatch_count for runner-owned retry logic

Changes from R2 feedback:
- Issue 1: DONE requires outcome=SUCCESS, ABANDONED requires outcome ∈ {FAILURE, CANCELLED, REJECTED}
- Issue 2: dispatch_count limit raised to 100
- Issue 3: Added BlackboardState.make_entry_key() helper
- Issue 4: SESSION_ID_PATTERN entropy increased to 64 bits (16 hex chars)
- Q1: Documented GROUP_APPEND at PROJECT scope uses written_by_group tracking
- Q2: event_id is auto-incrementing per task, managed by runner
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

# ============================================================================
# Session & Task Identity
# ============================================================================

SESSION_ID_PATTERN = r"^S[0-9a-f]{16}$"  # 64-bit entropy
TASK_ID_PATTERN = r"^T\d+(\.\d+)*$"  # T1, T1.2, T1.2.3


class SessionID(BaseModel):
    """Session identifier for a compose workflow run."""

    value: str = Field(
        pattern=SESSION_ID_PATTERN,
        description="Session ID format: S + 16 hex chars (64-bit entropy). Example: S1a2b3c4d5e6f7890"
    )

    @classmethod
    def generate(cls) -> SessionID:
        """Generate a new session ID with 64-bit entropy."""
        import secrets
        return cls(value=f"S{secrets.token_hex(8)}")


class TaskID(BaseModel):
    """Hierarchical task identifier within a session."""

    value: str = Field(
        pattern=TASK_ID_PATTERN,
        description="Hierarchical task ID. Example: T1.2.3 (3rd subtask of 2nd subtask of 1st root task)"
    )

    @property
    def depth(self) -> int:
        """Tree depth. T1 → 0, T1.2 → 1, T1.2.3 → 2"""
        return self.value.count(".")

    @property
    def parent(self) -> TaskID | None:
        """Parent task ID. T1.2.3 → T1.2, T1 → None"""
        parts = self.value.split(".")
        if len(parts) == 1:
            return None
        return TaskID(value=".".join(parts[:-1]))

    def is_ancestor_of(self, other: TaskID) -> bool:
        """Check if this task is an ancestor of another. T1.2 is ancestor of T1.2.3"""
        return other.value.startswith(self.value + ".")

    def is_descendant_of(self, other: TaskID) -> bool:
        """Check if this task is a descendant of another. T1.2.3 is descendant of T1.2"""
        return self.value.startswith(other.value + ".")


# ============================================================================
# Task Status & Outcome
# ============================================================================

class TaskStatus(str, Enum):
    """
    5-state machine aligned with MimoCode.

    Transitions:
    OPEN → IN_PROGRESS → DONE
    OPEN → IN_PROGRESS → BLOCKED → IN_PROGRESS (retry loop)
    OPEN → IN_PROGRESS → ABANDONED (permanent failure)
    """
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    ABANDONED = "abandoned"


class TaskOutcome(str, Enum):
    """
    Terminal outcome, gated to DONE/ABANDONED statuses.
    Preserves QuantCode risk gate granularity without polluting state machine.
    """
    SUCCESS = "success"      # Normal completion
    FAILURE = "failure"      # Technical error (e.g., API timeout, code bug)
    CANCELLED = "cancelled"  # User/system-initiated cancellation
    REJECTED = "rejected"    # Risk/validation gate rejection


# ============================================================================
# Groups & Blackboard Scope
# ============================================================================

class GroupName(str, Enum):
    """6 groups with HARD isolation walls."""
    RESEARCH = "research"
    FACTOR = "factor"
    BACKTEST = "backtest"
    STRATEGY = "strategy"
    PORTFOLIO = "portfolio"
    TRADE = "trade"


class BlackboardScope(str, Enum):
    """
    Visibility scope for blackboard entries.

    GLOBAL: Visible to all groups across all sessions (e.g., config, system state)
    PROJECT: Visible to all groups within this session (e.g., shared objectives)
    GROUP: Visible only within one group (e.g., MEMORY.md, working notes)
    TASK: Visible only to one task and its descendants (e.g., intermediate results)
    """
    GLOBAL = "global"
    PROJECT = "project"
    GROUP = "group"
    TASK = "task"


class WritePolicy(str, Enum):
    """
    Write semantics for blackboard entries.

    OWNER_ONLY: Only the owning group can write (strict isolation)
    GROUP_APPEND: Multiple groups can append, tracked by written_by_group
    PUBLIC: Any group can overwrite (use sparingly)
    """
    OWNER_ONLY = "owner_only"
    GROUP_APPEND = "group_append"
    PUBLIC = "public"


# ============================================================================
# Blackboard Entry
# ============================================================================

class BlackboardEntry(BaseModel):
    """
    A single key-value entry in the blackboard.

    GROUP_APPEND at PROJECT scope:
    - Entry is visible to all groups (PROJECT scope)
    - Multiple groups can append data (GROUP_APPEND policy)
    - Runner tracks which group wrote each piece via written_by_group
    - Example: Factor registry where Research and Factor groups both contribute
    """

    key: str = Field(
        min_length=1,
        description="Entry key within scope. Example: 'factor_registry', 'memory', 'progress'"
    )

    scope: BlackboardScope = Field(
        description="Visibility scope"
    )

    group: GroupName | None = Field(
        default=None,
        description="Owning group for GROUP scope, or None for wider scopes"
    )

    task_id: TaskID | None = Field(
        default=None,
        description="Owning task for TASK scope, or None for wider scopes"
    )

    value: Any = Field(
        description="Entry value (arbitrary JSON-serializable data)"
    )

    write_policy: WritePolicy = Field(
        default=WritePolicy.OWNER_ONLY,
        description="Write permission policy"
    )

    written_by_group: GroupName = Field(
        description="Group that last wrote this entry (for GROUP_APPEND audit)"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Creation timestamp (UTC)"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp (UTC)"
    )

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, dt: datetime, _info) -> int:
        """Serialize datetime to Unix epoch for JSON interop."""
        return int(dt.timestamp())

    @field_validator("scope")
    @classmethod
    def _validate_scope_constraints(cls, v: BlackboardScope, info) -> BlackboardScope:
        """Validate scope-specific field requirements."""
        return v

    @model_validator(mode="after")
    def _validate_scope_fields(self) -> BlackboardEntry:
        """Enforce scope-specific field requirements."""
        if self.scope == BlackboardScope.GROUP and self.group is None:
            raise ValueError("scope=GROUP requires `group` to be set")

        if self.scope == BlackboardScope.TASK and self.task_id is None:
            raise ValueError("scope=TASK requires `task_id` to be set")

        if self.scope in {BlackboardScope.GLOBAL, BlackboardScope.PROJECT}:
            if self.group is not None:
                raise ValueError(f"scope={self.scope.value} must have group=None")
            if self.task_id is not None:
                raise ValueError(f"scope={self.scope.value} must have task_id=None")

        return self

    @model_validator(mode="after")
    def _validate_write_policy(self) -> BlackboardEntry:
        """Validate write policy compatibility with scope."""
        if self.write_policy == WritePolicy.GROUP_APPEND and self.scope not in {
            BlackboardScope.GROUP, BlackboardScope.PROJECT
        }:
            raise ValueError("GROUP_APPEND policy only valid for GROUP/PROJECT scope")

        return self


# ============================================================================
# Blackboard State
# ============================================================================

class BlackboardState(BaseModel):
    """
    Global blackboard state for a session.

    Entry key format: <scope>:<group_or_'_'>:<key>
    Example: "group:research:memory", "project:_:objectives", "global:_:config"
    """

    session_id: SessionID = Field(
        description="Session this blackboard belongs to"
    )

    entries: dict[str, BlackboardEntry] = Field(
        default_factory=dict,
        description="Keyed by `<scope>:<group_or_'_'>:<key>` for O(1) lookup."
    )

    @staticmethod
    def make_entry_key(scope: BlackboardScope, group: GroupName | None, key: str) -> str:
        """
        Construct composite key for blackboard entry.

        Examples:
        - make_entry_key(GROUP, RESEARCH, "memory") → "group:research:memory"
        - make_entry_key(PROJECT, None, "objectives") → "project:_:objectives"
        - make_entry_key(GLOBAL, None, "config") → "global:_:config"
        """
        group_part = group.value if group else "_"
        return f"{scope.value}:{group_part}:{key}"

    def add_entry(self, entry: BlackboardEntry) -> None:
        """Add or update an entry in the blackboard."""
        key = self.make_entry_key(entry.scope, entry.group, entry.key)
        entry.updated_at = datetime.utcnow()
        self.entries[key] = entry

    def get_entry(self, scope: BlackboardScope, group: GroupName | None, key: str) -> BlackboardEntry | None:
        """Retrieve an entry by scope, group, and key."""
        composite_key = self.make_entry_key(scope, group, key)
        return self.entries.get(composite_key)

    def remove_entry(self, scope: BlackboardScope, group: GroupName | None, key: str) -> bool:
        """Remove an entry. Returns True if entry existed, False otherwise."""
        composite_key = self.make_entry_key(scope, group, key)
        if composite_key in self.entries:
            del self.entries[composite_key]
            return True
        return False


# ============================================================================
# Task Event (Audit Trail)
# ============================================================================

class EventKind(str, Enum):
    """Event types for task lifecycle audit trail."""
    CREATED = "created"
    ASSIGNED = "assigned"
    STARTED = "started"
    BLOCKED = "blocked"
    RESUMED = "resumed"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"
    HANDOFF = "handoff"  # QuantCode-specific: cross-group transition


class ComposeTaskEvent(BaseModel):
    """
    Append-only event log for task lifecycle.

    event_id sequencing:
    - Auto-incrementing integer per task (0, 1, 2, ...)
    - Runner manages sequence generation
    - Guarantees causal ordering within a task
    """

    event_id: int = Field(
        ge=0,
        description="Auto-incrementing sequence number per task (managed by runner)"
    )

    task_id: TaskID = Field(
        description="Task this event belongs to"
    )

    kind: EventKind = Field(
        description="Event type"
    )

    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Event timestamp (UTC)"
    )

    actor: str = Field(
        description="Agent, group, or system component that triggered this event"
    )

    message: str | None = Field(
        default=None,
        description="Human-readable event description"
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific metadata (e.g., error details, handoff context)"
    )

    # HANDOFF event fields
    from_group: GroupName | None = Field(
        default=None,
        description="Source group for HANDOFF events"
    )

    to_group: GroupName | None = Field(
        default=None,
        description="Target group for HANDOFF events"
    )

    @field_serializer("timestamp")
    def serialize_dt(self, dt: datetime, _info) -> int:
        """Serialize datetime to Unix epoch for JSON interop."""
        return int(dt.timestamp())

    @model_validator(mode="after")
    def _validate_handoff_fields(self) -> ComposeTaskEvent:
        """Validate HANDOFF event requires from_group and to_group."""
        if self.kind == EventKind.HANDOFF:
            if self.from_group is None or self.to_group is None:
                raise ValueError("HANDOFF event requires both from_group and to_group")
            if self.from_group == self.to_group:
                raise ValueError("HANDOFF event requires different from_group and to_group")
        else:
            if self.from_group is not None or self.to_group is not None:
                raise ValueError(f"from_group/to_group only valid for HANDOFF events, not {self.kind.value}")

        return self


# ============================================================================
# Compose Task
# ============================================================================

TIn = TypeVar("TIn")
TOut = TypeVar("TOut")


class ComposeTask(BaseModel, Generic[TIn, TOut]):
    """
    Generic compose task with type-safe input/output.

    Example:
        ComposeTask[FactorSpec, FactorResult] for factor computation
        ComposeTask[BacktestParams, BacktestReport] for backtesting

    Tree structure:
    - task_id (T1.2.3) encodes hierarchical position
    - internal_id (UUID) provides stable cross-references across renames
    - root_task_id must be prefix of task_id (validated)

    Status & Outcome:
    - status follows 5-state machine (open/in_progress/blocked/done/abandoned)
    - outcome is gated to terminal states:
        * DONE requires outcome=SUCCESS
        * ABANDONED requires outcome ∈ {FAILURE, CANCELLED, REJECTED}
    - Non-terminal states (OPEN, IN_PROGRESS, BLOCKED) must have outcome=None

    Retry & Dispatch:
    - dispatch_count tracks attempts (runner owns retry policy)
    - Hard limit of 100 attempts (configurable in runner logic)
    - last_error captures most recent failure details
    """

    # Identity
    task_id: TaskID = Field(
        description="Hierarchical task ID (T1.2.3). This IS the tree path."
    )

    internal_id: UUID = Field(
        default_factory=uuid4,
        description="Stable UUID for cross-references. Survives task_id renames."
    )

    root_task_id: TaskID = Field(
        description="Root task ID (e.g., T1 for T1.2.3). Must be prefix of task_id."
    )

    session_id: SessionID = Field(
        description="Session this task belongs to"
    )

    # Group & Agent
    group: GroupName = Field(
        description="Group responsible for this task"
    )

    agent_id: str | None = Field(
        default=None,
        description="ID of agent currently assigned to this task"
    )

    # Task Definition
    description: str = Field(
        min_length=1,
        description="Human-readable task description"
    )

    input_data: TIn = Field(
        description="Type-safe input data for this task"
    )

    output_data: TOut | None = Field(
        default=None,
        description="Type-safe output data (set when status=DONE)"
    )

    # Status & Outcome
    status: TaskStatus = Field(
        default=TaskStatus.OPEN,
        description="Current task status (5-state machine)"
    )

    outcome: TaskOutcome | None = Field(
        default=None,
        description="Terminal outcome (gated to DONE/ABANDONED statuses)"
    )

    # Retry & Error Tracking
    dispatch_count: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Number of times dispatched to an agent. Runner owns retry policy."
    )

    last_error: str | None = Field(
        default=None,
        description="Most recent error message (if status=BLOCKED or ABANDONED)"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Task creation timestamp (UTC)"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp (UTC)"
    )

    completed_at: datetime | None = Field(
        default=None,
        description="Completion timestamp (UTC, set when status=DONE or ABANDONED)"
    )

    # Event Log
    events: list[ComposeTaskEvent] = Field(
        default_factory=list,
        description="Append-only event log for audit trail"
    )

    @field_serializer("created_at", "updated_at", "completed_at")
    def serialize_dt(self, dt: datetime | None, _info) -> int | None:
        """Serialize datetime to Unix epoch for JSON interop."""
        if dt is None:
            return None
        return int(dt.timestamp())

    @model_validator(mode="after")
    def _validate_root_task_prefix(self) -> ComposeTask:
        """Validate root_task_id is prefix of task_id."""
        if not (
            self.task_id.value == self.root_task_id.value
            or self.task_id.is_descendant_of(self.root_task_id)
        ):
            raise ValueError(
                f"root_task_id '{self.root_task_id.value}' must be prefix of task_id '{self.task_id.value}'"
            )
        return self

    @model_validator(mode="after")
    def _validate_outcome_gating(self) -> ComposeTask:
        """
        Validate outcome is gated to terminal statuses.

        Rules:
        - DONE requires outcome=SUCCESS
        - ABANDONED requires outcome ∈ {FAILURE, CANCELLED, REJECTED}
        - Non-terminal states (OPEN, IN_PROGRESS, BLOCKED) require outcome=None
        """
        terminal_statuses = {TaskStatus.DONE, TaskStatus.ABANDONED}

        if self.status == TaskStatus.DONE:
            if self.outcome != TaskOutcome.SUCCESS:
                raise ValueError(
                    f"DONE status requires outcome=SUCCESS, got {self.outcome}"
                )

        elif self.status == TaskStatus.ABANDONED:
            if self.outcome not in {
                TaskOutcome.FAILURE,
                TaskOutcome.CANCELLED,
                TaskOutcome.REJECTED,
            }:
                raise ValueError(
                    f"ABANDONED status requires outcome ∈ {{FAILURE, CANCELLED, REJECTED}}, got {self.outcome}"
                )

        else:
            # Non-terminal statuses
            if self.outcome is not None:
                raise ValueError(
                    f"Non-terminal status {self.status.value} requires outcome=None, got {self.outcome}"
                )

        return self

    @model_validator(mode="after")
    def _validate_completed_at(self) -> ComposeTask:
        """Validate completed_at is set only for terminal statuses."""
        terminal_statuses = {TaskStatus.DONE, TaskStatus.ABANDONED}

        if self.status in terminal_statuses:
            if self.completed_at is None:
                # Auto-set if missing
                self.completed_at = datetime.utcnow()
        else:
            if self.completed_at is not None:
                raise ValueError(
                    f"completed_at must be None for non-terminal status {self.status.value}"
                )

        return self

    @model_validator(mode="after")
    def _validate_output_data(self) -> ComposeTask:
        """Validate output_data is set only for DONE status."""
        if self.status == TaskStatus.DONE:
            if self.output_data is None:
                raise ValueError("DONE status requires output_data to be set")
        else:
            if self.output_data is not None:
                raise ValueError(
                    f"output_data must be None for non-DONE status {self.status.value}"
                )

        return self

    def add_event(
        self,
        kind: EventKind,
        actor: str,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
        from_group: GroupName | None = None,
        to_group: GroupName | None = None,
    ) -> ComposeTaskEvent:
        """
        Add an event to the task's audit log.

        Automatically assigns the next event_id in sequence.
        """
        event = ComposeTaskEvent(
            event_id=len(self.events),
            task_id=self.task_id,
            kind=kind,
            actor=actor,
            message=message,
            metadata=metadata or {},
            from_group=from_group,
            to_group=to_group,
        )
        self.events.append(event)
        self.updated_at = datetime.utcnow()
        return event


# ============================================================================
# Session State
# ============================================================================

class SessionState(BaseModel):
    """
    Complete state for a compose workflow session.

    File layout:
    .quantcode/
      sessions/
        S1a2b3c4d5e6f7890/
          session.json              # This object
          blackboard.json           # BlackboardState
          memory/
            global/                 # GLOBAL scope memory
              config.md
            project/                # PROJECT scope memory
              objectives.md
            groups/                 # GROUP scope memory
              research/
                MEMORY.md
              factor/
                MEMORY.md
              ...
            tasks/                  # TASK scope memory
              T1/
                progress.md
              T1.2/
                progress.md
              ...
    """

    session_id: SessionID = Field(
        description="Unique session identifier"
    )

    root_tasks: list[ComposeTask] = Field(
        default_factory=list,
        description="Top-level tasks (T1, T2, T3, ...)"
    )

    blackboard: BlackboardState = Field(
        description="Shared blackboard state"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Session creation timestamp (UTC)"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp (UTC)"
    )

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, dt: datetime, _info) -> int:
        """Serialize datetime to Unix epoch for JSON interop."""
        return int(dt.timestamp())

    def all_tasks(self) -> list[ComposeTask]:
        """
        Flatten task tree into a list.

        Returns tasks in depth-first order (T1, T1.1, T1.2, T2, T2.1, ...).
        """
        result = []

        def visit(task: ComposeTask) -> None:
            result.append(task)
            # Note: Subtasks would be stored separately in the runner's task registry
            # This is a simplified view that only includes root tasks

        for task in self.root_tasks:
            visit(task)

        return result


# ============================================================================
# Validation Examples (for documentation/testing)
# ============================================================================

def _validation_example_1():
    """Example: Create a valid task with hierarchical ID."""
    session_id = SessionID.generate()

    task = ComposeTask[dict, dict](
        task_id=TaskID(value="T1.2"),
        root_task_id=TaskID(value="T1"),
        session_id=session_id,
        group=GroupName.RESEARCH,
        description="Fetch market data for AAPL",
        input_data={"ticker": "AAPL", "start_date": "2024-01-01"},
    )

    # Validate tree structure
    assert task.task_id.depth == 1
    assert task.task_id.parent == TaskID(value="T1")
    assert task.task_id.is_descendant_of(task.root_task_id)


def _validation_example_2():
    """Example: Transition task to DONE with outcome."""
    session_id = SessionID.generate()

    task = ComposeTask[dict, dict](
        task_id=TaskID(value="T1"),
        root_task_id=TaskID(value="T1"),
        session_id=session_id,
        group=GroupName.RESEARCH,
        description="Fetch market data",
        input_data={"ticker": "AAPL"},
    )

    # Transition to DONE
    task.status = TaskStatus.DONE
    task.outcome = TaskOutcome.SUCCESS
    task.output_data = {"data": [1, 2, 3]}

    # Validator will auto-set completed_at
    task = ComposeTask[dict, dict].model_validate(task.model_dump())
    assert task.completed_at is not None


def _validation_example_3():
    """Example: Blackboard entry with GROUP scope."""
    session_id = SessionID.generate()

    entry = BlackboardEntry(
        key="memory",
        scope=BlackboardScope.GROUP,
        group=GroupName.RESEARCH,
        value={"notes": "Market data collected"},
        write_policy=WritePolicy.OWNER_ONLY,
        written_by_group=GroupName.RESEARCH,
    )

    blackboard = BlackboardState(session_id=session_id)
    blackboard.add_entry(entry)

    # Retrieve entry
    retrieved = blackboard.get_entry(BlackboardScope.GROUP, GroupName.RESEARCH, "memory")
    assert retrieved is not None
    assert retrieved.key == "memory"


def _validation_example_4():
    """Example: HANDOFF event for cross-group transition."""
    session_id = SessionID.generate()
    task_id = TaskID(value="T1")

    event = ComposeTaskEvent(
        event_id=0,
        task_id=task_id,
        kind=EventKind.HANDOFF,
        actor="compose_runner",
        message="Research completed, handing off to Factor group",
        from_group=GroupName.RESEARCH,
        to_group=GroupName.FACTOR,
    )

    assert event.kind == EventKind.HANDOFF
    assert event.from_group == GroupName.RESEARCH
    assert event.to_group == GroupName.FACTOR


def _validation_example_5():
    """Example: Invalid outcome gating (should raise ValueError)."""
    session_id = SessionID.generate()

    try:
        # DONE with outcome=FAILURE should fail
        task = ComposeTask[dict, dict](
            task_id=TaskID(value="T1"),
            root_task_id=TaskID(value="T1"),
            session_id=session_id,
            group=GroupName.RESEARCH,
            description="Test task",
            input_data={},
            status=TaskStatus.DONE,
            outcome=TaskOutcome.FAILURE,  # Invalid!
            output_data={"result": "test"},
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "DONE status requires outcome=SUCCESS" in str(e)


def _validation_example_6():
    """Example: dispatch_count limit enforcement."""
    session_id = SessionID.generate()

    try:
        # dispatch_count > 100 should fail
        task = ComposeTask[dict, dict](
            task_id=TaskID(value="T1"),
            root_task_id=TaskID(value="T1"),
            session_id=session_id,
            group=GroupName.RESEARCH,
            description="Test task",
            input_data={},
            dispatch_count=101,  # Invalid!
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "le=100" in str(e) or "less than or equal to 100" in str(e)
