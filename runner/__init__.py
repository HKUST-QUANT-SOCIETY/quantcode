"""QuantCode runner 包：验收 / LangGraph / Compose 执行。

Day 1：acceptance + schema_validator
Day 2 尹一帆：langgraph_base + compose_executor（外加 memory 模块在 runner.memory）
"""

_ACCEPTANCE_EXPORTS = frozenset({"run_acceptance", "AcceptanceResult", "CheckResult"})
_SCHEMA_EXPORTS = frozenset({"validate_against_schema"})
_LANGGRAPH_EXPORTS = frozenset({
    "BaseFlowState", "PROJECT_ROOT", "DEFAULT_CHECKPOINT_DB", "create_workflow",
    "default_compose_edges", "get_checkpointer", "make_thread_id",
})
_COMPOSE_EXPORTS = frozenset({
    "FLOW_REGISTRY", "PRE_INVOKE_HOOKS", "execute_compose_flow", "list_registered_flows",
    "register_flow", "register_pre_invoke_hook", "clear_pre_invoke_hooks", "unregister_flow",
    "aexecute_compose_flow",
})


def __getattr__(name: str):
    """Load optional execution dependencies only for callers that need them."""
    if name in _ACCEPTANCE_EXPORTS:
        from . import acceptance
        return getattr(acceptance, name)
    if name in _SCHEMA_EXPORTS:
        from . import schema_validator
        return getattr(schema_validator, name)
    if name in _LANGGRAPH_EXPORTS:
        from . import langgraph_base
        return getattr(langgraph_base, name)
    if name in _COMPOSE_EXPORTS:
        from . import compose_executor
        return getattr(compose_executor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
