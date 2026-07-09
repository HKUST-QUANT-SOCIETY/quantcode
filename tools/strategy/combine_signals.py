"""combine_signals tool — 组合多信号权重（stub）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.registry import ToolDef


class CombineSignalsArgs(BaseModel):
    selected: list[dict] = Field(
        min_length=1,
        description="select_signals 输出的 selected 列表",
    )
    target_gross_exposure: float = Field(default=1.0, ge=0, le=2)


def combine_signals_execute(args: CombineSignalsArgs, ctx: dict) -> dict:
    hints = []
    for s in args.selected:
        h = s.get("weight_hint")
        hints.append(float(h) if h is not None and float(h) > 0 else 1.0)
    total = sum(hints) or 1.0
    weights = {
        s["signal_id"]: round(hints[i] / total * args.target_gross_exposure, 6)
        for i, s in enumerate(args.selected)
    }
    # fix rounding drift on last key
    if weights:
        keys = list(weights.keys())
        weights[keys[-1]] = round(
            args.target_gross_exposure - sum(weights[k] for k in keys[:-1]), 6
        )
    return {
        "weights": weights,
        "gross_exposure": round(sum(weights.values()), 6),
        "signal_ids": list(weights.keys()),
    }


combine_signals_tool = ToolDef(
    id="combine_signals",
    description=(
        "Combine selected signals into portfolio weights summing to target_gross_exposure. "
        "Input: selected[] from select_signals, optional target_gross_exposure. "
        "Returns weights{signal_id: weight} and gross_exposure."
    ),
    schema=CombineSignalsArgs,
    execute=combine_signals_execute,
)

__all__ = ["combine_signals_tool", "CombineSignalsArgs", "combine_signals_execute"]
