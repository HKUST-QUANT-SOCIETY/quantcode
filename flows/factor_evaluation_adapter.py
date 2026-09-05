"""Compatibility flow for the canonical QuantEvaluator package adapter."""
from __future__ import annotations

from os import PathLike
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict

from schemas import FactorSpec
from tools.factor.quant_evaluator_adapter import (
    QuantEvaluatorArgs,
    quant_evaluator_execute,
    unavailable_result,
)


class _EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_panel: dict[str, Any]
    label_bundle: dict[str, Any]
    metric_ids: tuple[str, ...] = (
        "rank_ic",
        "pearson_ic",
        "ic_ir",
        "coverage",
    )


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
    data = state["input_data"]
    if "factor_panel" in data or "label_bundle" in data:
        return {"input_spec": _EvaluationInput(**data).model_dump(mode="json")}
    return {"input_spec": FactorSpec(**data).model_dump(mode="json")}


def call_quant_evaluator(state: FactorEvaluationState) -> dict[str, Any]:
    payload = state["input_spec"]
    if "factor_panel" not in payload:
        result = unavailable_result(
            "FactorSpec is not a QuantEvaluator input. Supply a materialized FactorPanel and an "
            "explicit LabelBundle; the FactorEngine MaterializedResult adapter is not frozen yet."
        )
    else:
        result = quant_evaluator_execute(QuantEvaluatorArgs(**payload), {})
    errors = list(result.get("errors") or [])
    artifacts = [str(item["path"]) for item in result.get("artifacts", []) if item.get("path")]
    return {
        "component_result": result,
        "output_data": result,
        "artifacts": artifacts,
        "errors": errors,
    }


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
