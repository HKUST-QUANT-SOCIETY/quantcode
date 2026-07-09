"""dcf_valuation tool — 简化 DCF 估值 stub。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.registry import ToolDef


class DcfValuationArgs(BaseModel):
    target_identifier: str = Field(min_length=1)
    fcf_ttm: float = Field(gt=0)
    growth_rate: float = Field(default=0.08, ge=-0.5, le=0.5)
    wacc: float = Field(default=0.10, gt=0, lt=0.5)
    terminal_growth: float = Field(default=0.03, ge=-0.1, le=0.1)
    shares_outstanding_m: float = Field(default=800.0, gt=0)
    projection_years: int = Field(default=5, ge=1, le=20)


def dcf_valuation_execute(args: DcfValuationArgs, ctx: dict) -> dict:
    if args.wacc <= args.terminal_growth:
        raise ValueError("wacc must be greater than terminal_growth")

    fcf = args.fcf_ttm
    pv = 0.0
    for t in range(1, args.projection_years + 1):
        fcf *= 1 + args.growth_rate
        pv += fcf / ((1 + args.wacc) ** t)
    terminal_fcf = fcf * (1 + args.terminal_growth)
    terminal_value = terminal_fcf / (args.wacc - args.terminal_growth)
    pv += terminal_value / ((1 + args.wacc) ** args.projection_years)
    equity_value = pv
    price = equity_value / args.shares_outstanding_m

    return {
        "target_identifier": args.target_identifier,
        "enterprise_value": round(equity_value, 2),
        "equity_value": round(equity_value, 2),
        "fair_value_per_share": round(price, 2),
        "wacc": args.wacc,
        "growth_rate": args.growth_rate,
        "terminal_growth": args.terminal_growth,
        "projection_years": args.projection_years,
        "method": "gordon_dcf_stub",
    }


dcf_valuation_tool = ToolDef(
    id="dcf_valuation",
    description=(
        "Run a simplified Gordon DCF valuation (stub). "
        "Input: target_identifier, fcf_ttm, optional growth/wacc/shares. "
        "Returns fair_value_per_share and enterprise_value."
    ),
    schema=DcfValuationArgs,
    execute=dcf_valuation_execute,
)

__all__ = ["dcf_valuation_tool", "DcfValuationArgs", "dcf_valuation_execute"]
