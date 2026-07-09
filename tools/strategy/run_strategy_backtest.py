"""run_strategy_backtest tool — 组合回测 stub，产出 StrategyReport。"""
from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from schemas.strategy import (
    BacktestSummary,
    StrategyReport,
    StrategyVerdict,
)
from tools.registry import ToolDef


class RunStrategyBacktestArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    as_of_date: date
    weights: dict[str, float] = Field(min_length=1)
    lookback_days: int = Field(default=252, ge=20, le=1260)


def run_strategy_backtest_execute(args: RunStrategyBacktestArgs, ctx: dict) -> dict:
    n = len(args.weights)
    # Deterministic stub metrics from weight dispersion
    concentration = max(args.weights.values()) if args.weights else 1.0
    sharpe = round(1.4 - 0.3 * concentration, 3)
    max_dd = round(min(max(0.05 + 0.1 * concentration, 0.05), 0.35), 4)
    annual_return = round(0.08 + 0.04 * n / 10, 4)
    start = args.as_of_date - timedelta(days=args.lookback_days)

    verdict = StrategyVerdict.PASS
    fail_reasons: list[str] = []
    if max_dd > 0.25:
        verdict = StrategyVerdict.NEEDS_HUMAN
        fail_reasons.append(f"max_drawdown {max_dd} > 0.25")
    if sharpe < 0.5:
        verdict = StrategyVerdict.FAIL
        fail_reasons.append(f"sharpe {sharpe} < 0.5")

    report = StrategyReport(
        strategy_name=args.strategy_name,
        as_of_date=args.as_of_date,
        selected_signals=list(args.weights.keys()),
        weights=args.weights,
        backtest=BacktestSummary(
            start_date=start,
            end_date=args.as_of_date,
            annual_return=annual_return,
            sharpe=sharpe,
            max_drawdown=max_dd,
            turnover_monthly=round(0.15 + 0.02 * n, 3),
        ),
        verdict=verdict,
        fail_reasons=fail_reasons,
    )
    return report.model_dump(mode="json")


run_strategy_backtest_tool = ToolDef(
    id="run_strategy_backtest",
    description=(
        "Run a stub portfolio backtest for combined signal weights. "
        "Input: strategy_name, as_of_date, weights{signal_id: weight}. "
        "Returns StrategyReport JSON (selected_signals, weights, backtest, verdict)."
    ),
    schema=RunStrategyBacktestArgs,
    execute=run_strategy_backtest_execute,
)

__all__ = [
    "run_strategy_backtest_tool",
    "RunStrategyBacktestArgs",
    "run_strategy_backtest_execute",
]
