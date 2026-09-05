"""In-process adapter for the canonical ``quant_evaluator`` package.

QuantEvaluator is distributed as a Python package, not an HTTP service. This
module only translates versioned QuantCode contracts into the package's public
``FactorBatch`` / ``LabelBundle`` interface; it never calculates metrics or
manufactures labels itself.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from datetime import date, datetime, timezone
from enum import Enum
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.component_call_result import ComponentCallResult, ComponentResultStatus
from schemas.data_contracts import FactorPanel
from tools.registry import ToolDef
from tools.utils.paths import safe_filename_component


class QuantEvaluatorLabelInput(BaseModel):
    """Explicit labels required by QuantEvaluator; no timing is inferred."""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1)
    values: list[list[float | None]]
    horizon: int = Field(gt=0)
    execution_delay: int = Field(default=0, ge=0)
    decision_time: list[date]
    signal_available_time: list[date] = Field(default_factory=list)
    execution_time: list[date] = Field(default_factory=list)
    label_start_time: list[date]
    label_end_time: list[date]
    validity: list[list[bool]] | None = None
    source_ref: str = Field(min_length=1)
    calendar_ref: str | None = None
    price_convention: Literal["vwap_to_vwap"] = "vwap_to_vwap"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape_and_timing(self) -> "QuantEvaluatorLabelInput":
        rows = len(self.values)
        if not rows or not self.values[0]:
            raise ValueError("label values must be a non-empty time-by-asset matrix")
        widths = {len(row) for row in self.values}
        if len(widths) != 1:
            raise ValueError("label values rows must have a consistent asset width")
        for name in ("decision_time", "label_start_time", "label_end_time"):
            if len(getattr(self, name)) != rows:
                raise ValueError(f"{name} length must match label row count")
        for name in ("signal_available_time", "execution_time"):
            value = getattr(self, name)
            if value and len(value) != rows:
                raise ValueError(f"{name} length must match label row count")
        if self.validity is not None:
            if len(self.validity) != rows or any(
                len(mask_row) != len(self.values[0]) for mask_row in self.validity
            ):
                raise ValueError("label validity shape must match label values")
        return self


class QuantEvaluatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_panel: FactorPanel
    label_bundle: QuantEvaluatorLabelInput
    metric_ids: tuple[str, ...] = (
        "rank_ic",
        "pearson_ic",
        "ic_ir",
        "coverage",
    )


def _component_version() -> str:
    try:
        return metadata.version("quant_evaluator")
    except metadata.PackageNotFoundError:
        return "not-installed"


def _result(
    status: ComponentResultStatus,
    *,
    output_data: dict | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    return ComponentCallResult(
        component_id="quant-evaluator",
        component_version=_component_version(),
        contract_version="component-call-result.v1",
        environment="in-process",
        result_status=status,
        source="python:quant_evaluator.evaluate",
        observed_at=datetime.now(timezone.utc),
        output_data=output_data,
        artifacts=artifacts or [],
        warnings=warnings or [],
        errors=errors or [],
    ).model_dump(mode="json")


def unavailable_result(reason: str) -> dict:
    """Return an honest envelope when the canonical input seam is unavailable."""
    return _result(ComponentResultStatus.UNAVAILABLE, errors=[reason])


def _load_runtime():
    from quant_evaluator import evaluate
    from quant_evaluator.contracts.factor_batch import AxisRef, FactorBatch
    from quant_evaluator.contracts.label_bundle import LabelBundle

    return evaluate, AxisRef, FactorBatch, LabelBundle


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_artifact(payload: dict[str, Any], factor_id: str, ctx: dict) -> dict[str, Any]:
    from runner.langgraph_base import PROJECT_ROOT

    root = Path(ctx.get("artifact_root") or PROJECT_ROOT / "artifacts" / "factor").resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_filename_component(factor_id)}-quant-evaluator.json"
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded)
    return {
        "path": str(path),
        "media_type": "application/json",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size_bytes": len(encoded),
    }


def quant_evaluator_execute(args: QuantEvaluatorArgs, ctx: dict) -> dict:
    panel = args.factor_panel
    labels = args.label_bundle
    if labels.decision_time != panel.dates:
        return _result(
            ComponentResultStatus.FAILED,
            errors=["label decision_time must exactly match FactorPanel dates"],
        )
    if len(labels.values) != len(panel.dates) or len(labels.values[0]) != len(panel.assets):
        return _result(
            ComponentResultStatus.FAILED,
            errors=["label values shape must match FactorPanel time and asset axes"],
        )

    try:
        import numpy as np

        evaluate, AxisRef, FactorBatch, LabelBundle = _load_runtime()
    except (ImportError, ModuleNotFoundError):
        return unavailable_result(
            "quant_evaluator package is not installed; install the pinned component build"
        )

    try:
        factor_values = np.asarray(panel.values, dtype=np.float64)[:, :, np.newaxis]
        label_values = np.asarray(
            [[np.nan if cell is None else cell for cell in row] for row in labels.values],
            dtype=np.float64,
        )
        factor_batch = FactorBatch(
            factor_ids=(panel.factor_id,),
            time_axis=AxisRef(
                name="time",
                dtype="date",
                size=len(panel.dates),
                values=np.asarray(panel.dates, dtype=object),
            ),
            asset_axis=AxisRef(
                name="asset",
                dtype="str",
                size=len(panel.assets),
                values=np.asarray(panel.assets, dtype=object),
            ),
            values=factor_values,
            context_refs={
                "factor_version": panel.factor_version,
                "data_snapshot_id": panel.data_snapshot_id,
                "source_path": panel.source_path,
            },
        )
        label_bundle = LabelBundle(
            target_id=labels.target_id,
            values=label_values,
            horizon=labels.horizon,
            execution_delay=labels.execution_delay,
            decision_time=tuple(labels.decision_time),
            signal_available_time=tuple(labels.signal_available_time),
            execution_time=tuple(labels.execution_time),
            label_start_time=tuple(labels.label_start_time),
            label_end_time=tuple(labels.label_end_time),
            validity=(
                np.asarray(labels.validity, dtype=bool) if labels.validity is not None else None
            ),
            source_ref=labels.source_ref,
            calendar_ref=labels.calendar_ref,
            price_convention=labels.price_convention,
            metadata=dict(labels.metadata),
        )
        bundle = evaluate(factor_batch, label_bundle, metrics=args.metric_ids)
        output = _jsonable(bundle)
        artifact_payload = {
            "component": {"id": "quant-evaluator", "version": _component_version()},
            "input": {
                "factor_id": panel.factor_id,
                "factor_version": panel.factor_version,
                "data_snapshot_id": panel.data_snapshot_id,
                "label_id": labels.target_id,
                "label_source_ref": labels.source_ref,
                "metric_ids": list(args.metric_ids),
            },
            "output": output,
        }
        artifact = _write_artifact(artifact_payload, panel.factor_id, ctx)
    except (TypeError, ValueError) as exc:
        return _result(
            ComponentResultStatus.FAILED,
            errors=[f"QuantEvaluator contract rejected input: {exc}"],
        )
    except Exception as exc:
        return _result(
            ComponentResultStatus.FAILED,
            errors=[f"QuantEvaluator execution failed: {type(exc).__name__}: {exc}"],
        )
    return _result(
        ComponentResultStatus.SUCCEEDED,
        output_data=output,
        artifacts=[artifact],
        warnings=list(output.get("warnings") or []) if isinstance(output, dict) else [],
    )


quant_evaluator_tool = ToolDef(
    id="quant_evaluator",
    description=(
        "Evaluate an explicit FactorPanel and LabelBundle through the installed canonical "
        "quant_evaluator Python package. The adapter never derives labels or computes fallback metrics."
    ),
    schema=QuantEvaluatorArgs,
    execute=quant_evaluator_execute,
)


__all__ = [
    "QuantEvaluatorArgs",
    "QuantEvaluatorLabelInput",
    "quant_evaluator_tool",
    "quant_evaluator_execute",
    "unavailable_result",
]
