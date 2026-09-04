"""Deterministic compatibility flow for the canonical QuantEvaluator adapter."""
from __future__ import annotations

from os import PathLike
from typing import Any, TypedDict

from schemas import FactorSpec
from tools.factor.quant_evaluator_adapter import QuantEvaluatorArgs, quant_evaluator_execute


class FactorEvaluationState(TypedDict, total=False):
    group: str
    flow_name: str
    input_data: dict[str, Any]
    input_spec: dict[str, Any]
    component_result: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: list[str]
    errors: list[str]
    _memory: Any


def _memory(state: FactorEvaluationState) -> Any:
    """Resolve the Compose executor's in-process Memory handle."""
    handle = state.get("_memory")
    if isinstance(handle, dict) and "_tid" in handle:
        from runner.compose_executor import get_memory

        return get_memory(handle["_tid"])
    return None


def validate_factor_spec(state: FactorEvaluationState) -> dict[str, Any]:
    return {"input_spec": FactorSpec(**state["input_data"]).model_dump(mode="json")}


def call_quant_evaluator(state: FactorEvaluationState) -> dict[str, Any]:
    result = quant_evaluator_execute(QuantEvaluatorArgs(spec=state["input_spec"]), {})
    errors = list(result.get("errors") or [])
    return {"component_result": result, "output_data": result, "errors": errors}


def build_workflow(checkpoint_db: str | PathLike[str] | None = None):
    from runner.langgraph_base import create_workflow, default_compose_edges, get_checkpointer

    workflow = create_workflow(
        {"validate": validate_factor_spec, "quant_evaluator": call_quant_evaluator},
        default_compose_edges(["validate", "quant_evaluator"]),
        state_schema=FactorEvaluationState,
    )
    return workflow.compile(checkpointer=get_checkpointer(checkpoint_db))


__all__ = [
    "FactorEvaluationState",
    "_memory",
    "validate_factor_spec",
    "call_quant_evaluator",
    "build_workflow",
]
