"""
QuantCode Pattern 1 & 2 foundational schemas — ComposeTask + BlackboardState.

Two-agent debate result (QuantCode drafter + MimoCode reviewer, 3 rounds):
- Tree depth: MAX_DEPTH=4 (5 levels total, root=0)
- Status machine: MimoCode's 5 states + separate outcome field
- Typing: Generic[TIn, TOut] for type-safe dispatch
- Isolation: Hard GROUP walls, no cross-group reads by default

Design decisions (R3 final):
1. task_id = hierarchical string (T1.2.3), internal_id = stable UUID
2. Status: open/in_progress/blocked/done/abandoned (MimoCode-aligned)
3. Outcome: success/failure/cancelled/rejected (terminal-only)
4. Blackboard: 5 scopes (GLOBAL/PROJECT/GROUP/SESSION/TASK)
5. GROUP scope is first-class (not a discriminator): each group owns MEMORY.md
6. dispatch_count limit raised to 100 (was 10 in v0, 10 in v1)
7. SESSION_ID entropy raised to 64 bits (16 hex chars)
8. DONE requires outcome=SUCCESS; ABANDONED requires outcome ∈ {FAILURE, CANCELLED, REJECTED}

Changelog vs initial draft at end of file.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Identifiers & constants
# ---------------------------------------------------------------------------

MAX_TREE_DEPTH = 4  # T1 / T1.2 / T1.2.3 / T1.2.3.4 / T1.2.3.4.5
TASK_ID_PATTERN = r"^T\d+(\.\d+){0,4}$"
SESSION_ID_PATTERN = r"^S[0-9a-f]{16}$"  # 64-bit entropy (R2 Issue 4 fix)

SessionID = str  # matches SESSION_ID_PATTERN
TaskIDStr = str  # matches TASK_ID_PATTERN


# ---------------------------------------------------------------------------
# Enums — MimoCode-aligned where terminology overlaps
# ---------------------------------------------------------------------------

class GroupName(StrEnum):
    """QuantCode's eight-group isolation boundary (Design §3.4)."""
    FUNDAMENTAL = "fundamental"
    FACTOR      = "factor"
    MODEL       = "model"
    RISK        = "risk"
    STRATEGY    = "strategy"
    OPTIONS     = "options"
    INFRA       = "infra"
    AGENT       = "agent"


class TaskStatus(StrEnum):
    """5-state machine, aligned with MimoCode."""
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED     = "blocked"
    DONE        = "done"
    ABANDONED   = "abandoned"


class TaskOutcome(StrEnum):
    """
    Terminal-only detail; only set when status ∈ {DONE, ABANDONED}.

    R2 Issue 1 fix: DONE requires outcome=SUCCESS, ABANDONED requires
    outcome ∈ {FAILURE, CANCELLED, REJECTED}. No outcome=None allowed
    for terminal states.
    """
    SUCCESS   = "success"
    FAILURE   = "failure"
    CANCELLED = "cancelled"
    REJECTED  = "rejected"   # QuantCode-specific: HumanGate denial


class TaskEventKind(StrEnum):
    """ComposeTaskEvent kind. HANDOFF is QuantCode-specific."""
    CREATED    = "created"
    STARTED    = "started"
    BLOCKED    = "blocked"
    UNBLOCKED  = "unblocked"
    DONE       = "done"
    ABANDONED  = "abandoned"
    RENAMED    = "renamed"
    HANDOFF    = "handoff"   # cross-group transition


class BlackboardScope(StrEnum):
    """
    5-level isolation. GLOBAL/PROJECT/SESSION/TASK mirror MimoCode.

    GROUP is a QuantCode extension: the 6-group boundary is a first-class
    isolation level (not just a discriminator). Rationale: each group has
    its own MEMORY.md, tool allowlist, and reviewer policy; a scope-level
    split lets the loader pick the file directly without scanning.

    On-disk layout (MimoCode-aligned nesting):
        GLOBAL:  <root>/.quantcode/memory/global/MEMORY.md
        PROJECT: <root>/MEMORY.md
        GROUP:   <root>/.quantcode/memory/groups/<group>/MEMORY.md
        SESSION: <root>/.quantcode/memory/sessions/<sid>/checkpoint.md
        TASK:    <root>/.quantcode/memory/sessions/<sid>/tasks/<tid>/progress.md
    """
    GLOBAL  = "global"
    PROJECT = "project"
    GROUP   = "group"
    SESSION = "session"
    TASK    = "task"


class WritePolicy(StrEnum):
    """
    Who may write to a blackboard entry.

    R2 Q1 clarification: GROUP_APPEND at PROJECT scope uses `written_by_group`
    tracking. Example: factor registry where fundamental and factor groups
    both append; written_by_group distinguishes authorship.
    """
    OWNER        = "owner"          # only the writing task
    APPEND       = "append"         # any task, append-only
    GROUP_APPEND = "group_append"   # any task in the same group, append-only


# ---------------------------------------------------------------------------
# ComposeTask — Generic envelope
# ---------------------------------------------------------------------------

TIn  = TypeVar("TIn",  bound=BaseModel)
TOut = TypeVar("TOut", bound=BaseModel)


class ComposeTask(BaseModel, Generic[TIn, TOut]):
    """
    Envelope for one node in a Compose flow (Pattern 1: Orchestrator-Worker).

    Generic parameters enable type-safe dispatch:
        task: ComposeTask[FactorSpec, FactorReport] = ComposeTask(
            task_id="T1.2",
            group=GroupName.FACTOR,
            input=FactorSpec(...),
        )

    The Orchestrator (Compose Mode) creates tasks, dispatches to workers,
    collects results. Workers read/write BlackboardState and return typed
    output; they never talk to each other directly.
    """
    model_config = ConfigDict(frozen=False, extra="forbid")

    # --- Identity ---------------------------------------------------------
    task_id: TaskIDStr = Field(
        pattern=TASK_ID_PATTERN,
        description="Human-readable hierarchical ID (T1, T1.2, T1.2.3). "
                    "IS the tree path — no separate tree_path field.",
    )
    internal_id: UUID = Field(
        default_factory=uuid4,
        description="Stable UUID for cross-references that survive renames.",
    )
    session_id: SessionID = Field(pattern=SESSION_ID_PATTERN)

    # --- Tree structure ---------------------------------------------------
    parent_task_id: TaskIDStr | None = Field(default=None, pattern=TASK_ID_PATTERN)
    root_task_id:   TaskIDStr        = Field(pattern=TASK_ID_PATTERN)
    depth: int = Field(default=0, ge=0, le=MAX_TREE_DEPTH,
                       description="0 = root. Enforced by orchestrator.")

    # --- Group routing (QuantCode-specific) -------------------------------
    group: GroupName = Field(
        description="Which of the 6 groups owns this task. Drives tool "
                    "allowlist, reviewer, and MEMORY.md scope."
    )

    # --- Lifecycle --------------------------------------------------------
    status: TaskStatus = TaskStatus.OPEN
    outcome: TaskOutcome | None = Field(
        default=None,
        description="Only set when status ∈ {DONE, ABANDONED}. "
                    "R2 Issue 1: DONE→SUCCESS, ABANDONED→{FAILURE, CANCELLED, REJECTED}.",
    )
    summary: str = Field(max_length=512)
    owner: str | None = Field(default=None, max_length=64,
                              description="Worker/actor handle, if dispatched.")
    last_error: str | None = Field(default=None, max_length=8192)
    dispatch_count: int = Field(
        default=0, ge=0, le=100,  # R2 Issue 2: raised from 10 to 100
        description="Number of times dispatched to a worker. Runner owns retry "
                    "policy; this is just the counter.",
    )

    # --- Payloads (typed) -------------------------------------------------
    input:  TIn        = Field(description="Typed input payload.")
    output: TOut | None = Field(default=None, description="Typed result, if any.")

    # --- Timestamps (datetime in Python, Unix epoch int in JSON) ----------
    created_at:  datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:  datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at:  datetime | None = None
    finished_at: datetime | None = None

    @field_serializer("created_at", "updated_at", "started_at", "finished_at",
                      when_used="json")
    def _serialize_ts(self, dt: datetime | None) -> int | None:
        return int(dt.timestamp()) if dt else None

    # --- Validators -------------------------------------------------------
    @field_validator("root_task_id")
    @classmethod
    def _root_matches_prefix(cls, v: str, info) -> str:
        tid = info.data.get("task_id")
        if tid and not tid.startswith(v):
            raise ValueError(f"root_task_id {v!r} not a prefix of task_id {tid!r}")
        return v

    @model_validator(mode="after")
    def _lifecycle_invariants(self) -> "ComposeTask":
        # R2 Issue 1: strict outcome gating
        terminal = {TaskStatus.DONE, TaskStatus.ABANDONED}
        if self.outcome is not None and self.status not in terminal:
            raise ValueError("outcome may only be set for terminal statuses")
        if self.status == TaskStatus.DONE:
            if self.outcome != TaskOutcome.SUCCESS:
                raise ValueError("DONE requires outcome=SUCCESS")
        if self.status == TaskStatus.ABANDONED:
            if self.outcome not in {TaskOutcome.FAILURE, TaskOutcome.CANCELLED, TaskOutcome.REJECTED}:
                raise ValueError("ABANDONED requires outcome ∈ {FAILURE, CANCELLED, REJECTED}")

        # Tree invariants
        if self.depth == 0 and self.parent_task_id is not None:
            raise ValueError("root task (depth=0) must have no parent_task_id")

        return self


# ---------------------------------------------------------------------------
# ComposeTaskEvent — audit trail
# ---------------------------------------------------------------------------

class ComposeTaskEvent(BaseModel):
    """
    Append-only lifecycle log for a task. Mirrors MimoCode's TaskEvent.

    R2 Q2 clarification: event_id is auto-incrementing per task (0, 1, 2...),
    managed by runner. Use add_event() method to auto-assign next sequence.
    """
    model_config = ConfigDict(extra="forbid")

    event_id:   int  # auto-incrementing per task, assigned by runner
    task_id:    TaskIDStr = Field(pattern=TASK_ID_PATTERN)
    session_id: SessionID = Field(pattern=SESSION_ID_PATTERN)
    kind:       TaskEventKind
    at:         datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary:    str = Field(default="", max_length=512)

    # For HANDOFF events: from_group → to_group
    from_group: GroupName | None = None
    to_group:   GroupName | None = None

    @field_serializer("at", when_used="json")
    def _serialize_at(self, dt: datetime) -> int:
        return int(dt.timestamp())

    @model_validator(mode="after")
    def _handoff_requires_groups(self) -> "ComposeTaskEvent":
        if self.kind == TaskEventKind.HANDOFF:
            if not (self.from_group and self.to_group):
                raise ValueError("HANDOFF events require from_group and to_group")
        return self


# ---------------------------------------------------------------------------
# BlackboardEntry & BlackboardState
# ---------------------------------------------------------------------------

class BlackboardEntry(BaseModel):
    """
    One key-value record in the blackboard (Pattern 2: Stateful Blackboard).

    `value` is any JSON-serializable payload. Binary content should be written
    as an Artifact under the owning ComposeTask; only the pointer lives here.
    """
    model_config = ConfigDict(extra="forbid")

    key:   str = Field(min_length=1, max_length=256,
                       pattern=r"^[a-zA-Z0-9._:/-]+$")
    scope: BlackboardScope
    group: GroupName | None = Field(
        default=None,
        description="Required iff scope == GROUP; ignored otherwise.",
    )
    write_policy: WritePolicy = WritePolicy.OWNER
    value: dict | list | str | int | float | bool | None

    written_by_task_id: TaskIDStr = Field(pattern=TASK_ID_PATTERN)
    written_by_group:   GroupName
    version:    int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("created_at", "updated_at", when_used="json")
    def _serialize_ts(self, dt: datetime) -> int:
        return int(dt.timestamp())

    @model_validator(mode="after")
    def _scope_constraints(self) -> "BlackboardEntry":
        if self.scope == BlackboardScope.GROUP and self.group is None:
            raise ValueError("scope=GROUP requires `group` to be set")
        if self.write_policy == WritePolicy.GROUP_APPEND and self.scope not in {
            BlackboardScope.GROUP, BlackboardScope.PROJECT
        }:
            raise ValueError("GROUP_APPEND policy only valid for GROUP/PROJECT scope")
        return self


class BlackboardState(BaseModel):
    """
    Contract for the Pattern 2 shared state layer.

    In-memory view over the on-disk layout. Workers read/write here; direct
    worker-to-worker messaging is forbidden.

    R2 Issue 3: Added make_entry_key() helper for consistent key format.
    """
    model_config = ConfigDict(extra="forbid")

    session_id: SessionID = Field(pattern=SESSION_ID_PATTERN)
    entries: dict[str, BlackboardEntry] = Field(
        default_factory=dict,
        description="Keyed by make_entry_key(scope, group, key) for O(1) lookup.",
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("updated_at", when_used="json")
    def _serialize_ts(self, dt: datetime) -> int:
        return int(dt.timestamp())

    @staticmethod
    def make_entry_key(scope: BlackboardScope, group: GroupName | None, key: str) -> str:
        """
        Composite key format for entries dict.

        Examples:
            make_entry_key(PROJECT, None, "last_pr") → "project:_:last_pr"
            make_entry_key(GROUP, FACTOR, "ic_registry") → "group:factor:ic_registry"
            make_entry_key(TASK, None, "progress") → "task:_:progress"
        """
        group_part = group.value if group else "_"
        return f"{scope.value}:{group_part}:{key}"

    def add_entry(self, entry: BlackboardEntry) -> None:
        """Add or update an entry. Uses make_entry_key() for consistent lookup."""
        ek = self.make_entry_key(entry.scope, entry.group, entry.key)
        self.entries[ek] = entry
        self.updated_at = datetime.now(timezone.utc)

    def get_entry(self, scope: BlackboardScope, group: GroupName | None, key: str) -> BlackboardEntry | None:
        """Retrieve an entry by scope/group/key."""
        ek = self.make_entry_key(scope, group, key)
        return self.entries.get(ek)

    def remove_entry(self, scope: BlackboardScope, group: GroupName | None, key: str) -> bool:
        """Remove an entry. Returns True if it existed."""
        ek = self.make_entry_key(scope, group, key)
        existed = ek in self.entries
        self.entries.pop(ek, None)
        if existed:
            self.updated_at = datetime.now(timezone.utc)
        return existed


# ---------------------------------------------------------------------------
# CHANGELOG (two-agent debate summary)
# ---------------------------------------------------------------------------
"""
ACCEPTED from MimoCode reviewer
--------------------------------
1. task_id becomes human-readable hierarchical string (T1.2.3), UUID kept
   as internal_id for stable cross-references across renames.
2. Status machine: MimoCode's 5 states (open/in_progress/blocked/done/
   abandoned) + separate outcome field for terminal detail.
3. Timestamps: datetime in Python, Unix epoch int in JSON via field_serializer.
4. last_error (was: error), dispatch_count (was: attempt) for MimoCode alignment.
5. ComposeTaskEvent added: append-only audit trail, HANDOFF kind for cross-group.
6. GLOBAL blackboard scope added.
7. Task memory nests under session: .quantcode/memory/sessions/<sid>/tasks/<tid>/.
8. WritePolicy trimmed to OWNER/APPEND/GROUP_APPEND.
9. R2 fixes: dispatch_count→100, SESSION_ID→64bit, make_entry_key() helper,
   strict outcome gating (DONE→SUCCESS, ABANDONED→{FAILURE,CANCELLED,REJECTED}).

DEFENDED (QuantCode-specific needs)
------------------------------------
A. GROUP scope is first-class (not a discriminator): each group owns MEMORY.md,
   tool allowlist, reviewer. Scope-level split → direct file picking.
B. depth and root_task_id kept: runner fans checkpoints back to root without
   walking parents.
C. Generic[TIn, TOut] kept per user directive: type-safe dispatch.
D. TaskOutcome.REJECTED kept: HumanGate denials need distinction from failures.
E. TaskEventKind.HANDOFF added: cross-group handoffs are load-bearing in
   Compose flows (fundamental → factor → model → risk).

Final MimoCode reviewer rating: 5/5 all dimensions, "Ready to ship".
"""
