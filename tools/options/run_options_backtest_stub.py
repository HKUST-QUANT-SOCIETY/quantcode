"""run_options_backtest_stub tool — 期权策略回测占位实现。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from schemas.options import OptionsBacktestReport
from tools.registry import ToolDef


class RunOptionsBacktestArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    underlying: str = Field(min_length=1)
    start_date: date
    end_date: date


def run_options_backtest_execute(args: RunOptionsBacktestArgs, ctx: dict) -> dict:
    days = (args.end_date - args.start_date).days
    report = OptionsBacktestReport(
        strategy_name=args.strategy_name,
        period_start=args.start_date,
        period_end=args.end_date,
        total_pnl=round(1200.0 + days * 3.5, 2),
        max_drawdown=0.06,
        sharpe=1.15,
        trade_count=max(days // 7, 1),
        notes=f"stub backtest for {args.underlying}",
    )
    return report.model_dump(mode="json")


run_options_backtest_stub_tool = ToolDef(
    id="run_options_backtest_stub",
    description=(
        "Run a stub options strategy backtest. "
        "Input: strategy_name, underlying, start_date, end_date. "
        "Returns OptionsBacktestReport JSON with pnl and risk metrics."
    ),
    schema=RunOptionsBacktestArgs,
    execute=run_options_backtest_execute,
)

__all__ = [
    "run_options_backtest_stub_tool",
    "RunOptionsBacktestArgs",
    "run_options_backtest_execute",
]
