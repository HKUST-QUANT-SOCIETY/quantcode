"""QuantCode Pydantic schemas.

Pydantic v2 is the Source of Truth (per Design §5.5). JSON Schema is
generated from Pydantic via `model_json_schema()`; JSON files under this
directory are legacy JSON Schema artefacts kept for CI validation until
callers migrate to Pydantic.

Foundational schemas (Pattern 1 + Pattern 2 contracts):
- ComposeTask       — task envelope (Pattern 1: Orchestrator-Worker)
- BlackboardState   — shared state layer (Pattern 2: Stateful Blackboard)
- ComposeTaskEvent  — append-only audit trail
"""
from .compose_task import (
    BlackboardEntry,
    BlackboardScope,
    BlackboardState,
    ComposeTask,
    ComposeTaskEvent,
    GroupName,
    MAX_TREE_DEPTH,
    SESSION_ID_PATTERN,
    TASK_ID_PATTERN,
    TaskEventKind,
    TaskOutcome,
    TaskStatus,
    WritePolicy,
)

__all__ = [
    "BlackboardEntry",
    "BlackboardScope",
    "BlackboardState",
    "ComposeTask",
    "ComposeTaskEvent",
    "GroupName",
    "MAX_TREE_DEPTH",
    "SESSION_ID_PATTERN",
    "TASK_ID_PATTERN",
    "TaskEventKind",
    "TaskOutcome",
    "TaskStatus",
    "WritePolicy",
]

# T4 factor schemas (肖骥超).
from .factor import (  # noqa: E402
    DateRange,
    DecayMetrics,
    FactorReport,
    FactorSpec,
    FactorVerdict,
    ICMetrics,
    ICMethod,
    LayeredBacktest,
    TurnoverMetrics,
)

__all__.extend([
    "DateRange",
    "DecayMetrics",
    "FactorReport",
    "FactorSpec",
    "FactorVerdict",
    "ICMetrics",
    "ICMethod",
    "LayeredBacktest",
    "TurnoverMetrics",
])
