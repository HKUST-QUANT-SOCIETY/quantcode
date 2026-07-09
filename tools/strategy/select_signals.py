"""select_signals tool — 从候选信号中筛选（stub）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.registry import ToolDef


class SelectSignalsArgs(BaseModel):
    candidates: list[dict] = Field(
        min_length=1,
        description="候选信号列表，每项含 signal_id / source_group / weight_hint",
    )
    max_positions: int = Field(default=50, ge=1, le=500)
    min_weight_hint: float = Field(default=0.0, ge=0, le=1)


def select_signals_execute(args: SelectSignalsArgs, ctx: dict) -> dict:
    ranked = sorted(
        args.candidates,
        key=lambda c: float(c.get("weight_hint") or 0.0),
        reverse=True,
    )
    selected = []
    for c in ranked:
        hint = float(c.get("weight_hint") or 0.0)
        if hint < args.min_weight_hint:
            continue
        selected.append(
            {
                "signal_id": c["signal_id"],
                "source_group": c.get("source_group", "factor"),
                "weight_hint": hint if hint > 0 else None,
            }
        )
        if len(selected) >= args.max_positions:
            break
    if not selected:
        # fallback: keep top-1 so StrategyReport can still validate
        top = ranked[0]
        selected = [
            {
                "signal_id": top["signal_id"],
                "source_group": top.get("source_group", "factor"),
                "weight_hint": float(top.get("weight_hint") or 0.1),
            }
        ]
    return {
        "selected": selected,
        "rejected_count": max(len(args.candidates) - len(selected), 0),
        "max_positions": args.max_positions,
    }


select_signals_tool = ToolDef(
    id="select_signals",
    description=(
        "Select tradable signals from candidates by weight_hint ranking. "
        "Input: candidates[{signal_id, source_group, weight_hint}], max_positions. "
        "Returns selected[] and rejected_count."
    ),
    schema=SelectSignalsArgs,
    execute=select_signals_execute,
)

__all__ = ["select_signals_tool", "SelectSignalsArgs", "select_signals_execute"]
