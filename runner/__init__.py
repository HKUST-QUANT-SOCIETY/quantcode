"""QuantCode runner 包：验收 / LangGraph / Compose 执行。

Day 1：acceptance + schema_validator
Day 2 尹一帆：langgraph_base + compose_executor（外加 memory 模块在 runner.memory）
"""

from .acceptance import run_acceptance, AcceptanceResult, CheckResult
from .schema_validator import validate_against_schema

from .langgraph_base import (
    BaseFlowState,
    PROJECT_ROOT,
    DEFAULT_CHECKPOINT_DB,
    create_workflow,
    default_compose_edges,
    get_checkpointer,
    make_thread_id,
)

from .compose_executor import (
    FLOW_REGISTRY,
    PRE_INVOKE_HOOKS,
    execute_compose_flow,
    list_registered_flows,
    register_flow,
    register_pre_invoke_hook,
    clear_pre_invoke_hooks,
    unregister_flow,
    aexecute_compose_flow,
)

__all__ = [
    # Day 1
    "run_acceptance",
    "AcceptanceResult",
    "CheckResult",
    "validate_against_schema",
    # Day 2 — LangGraph base
    "BaseFlowState",
    "PROJECT_ROOT",
    "DEFAULT_CHECKPOINT_DB",
    "create_workflow",
    "default_compose_edges",
    "get_checkpointer",
    "make_thread_id",
    # Day 2 — Compose executor
    "FLOW_REGISTRY",
    "PRE_INVOKE_HOOKS",
    "execute_compose_flow",
    "list_registered_flows",
    "register_flow",
    "register_pre_invoke_hook",
    "clear_pre_invoke_hooks",
    "unregister_flow",
    "aexecute_compose_flow",
]
__version__ = "0.0.2"
