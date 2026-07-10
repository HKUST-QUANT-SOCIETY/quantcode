"""calc_risk_stub tool — 提供 normal/high_risk 两种风控场景数据。"""
from __future__ import annotations

from tools.registry import ToolDef
from tools.risk_stub import CalcRiskStubArgs, calc_risk_stub

calc_risk_stub_tool = ToolDef(
    id="calc_risk_stub",
    description=(
        "Compute risk metrics for a given scenario. "
        "Returns {tail_risk_var_99, max_drawdown, volatility, position_limit, "
        "correlation_with_existing, var_99_trend, max_drawdown_trend, thresholds}. "
        "Use 'normal' to get safe metrics, 'high_risk' to get metrics that exceed thresholds."
    ),
    schema=CalcRiskStubArgs,
    execute=lambda args, ctx: calc_risk_stub(args.scenario),
)

__all__ = ["calc_risk_stub_tool"]
