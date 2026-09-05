"""run_options_backtest tool（历史 id：run_options_backtest_stub，保留以防链路断）。

Day6 真实化：原常数 pnl 占位已替换为 tools/options/backtest_engine.py 的
逐日 BS 盯市引擎（engine: "options_v1"）。旧签名（strategy_name/underlying/
start_date/end_date）不变；可选 underlying_prices / positions 缺省时用
确定性合成价格 + 单腿 ATM call 合成，保证旧行为可复现（对齐
run_strategy_backtest 的合成价格捷径）。腿规格 {leg_type, strike,
expiry_offset_days, quantity} 每期全量给（换仓语义同 weights）。
# ponytail: 合成价格是引擎无行情输入时的捷径，接真实行情序列后由调用方直接传。
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from pydantic import BaseModel, Field

from schemas.options import OptionsBacktestReport
from tools.options.backtest_engine import ENGINE_VERSION, run_options_backtest
from tools.registry import ToolDef


class RunOptionsBacktestArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    underlying: str = Field(min_length=1)
    start_date: date
    end_date: date
    underlying_prices: list[float] | None = Field(
        default=None,
        description="标的收盘序列（len == positions）；缺省用确定性合成价格",
    )
    positions: list[list[dict]] | None = Field(
        default=None,
        description="每日期权腿集合 leg={leg_type,strike,expiry_offset_days,quantity}；缺省单腿 ATM call",
    )


def _synthetic_prices(underlying: str, n: int) -> list[float]:
    """确定式合成价格：按标的名哈希定相位 + 恒正小漂移（复用 strategy 口径）。"""
    seed = int.from_bytes(underlying.encode("utf-8")[:8], "big")
    phase = (seed % 97 + 1) / 7.0
    px = 100.0
    series = [px]
    for t in range(1, n):
        r = 0.12 / 365.0 + 0.004 * math.sin(phase + t / 3.0)
        px *= math.exp(r)
        series.append(px)
    return series


def run_options_backtest_execute(args: RunOptionsBacktestArgs, ctx: dict) -> dict:
    days = (args.end_date - args.start_date).days
    if days <= 0:
        report = OptionsBacktestReport(
            strategy_name=args.strategy_name,
            period_start=args.start_date,
            period_end=args.end_date,
            total_pnl=0.0,
            max_drawdown=0.0,
            sharpe=None,
            trade_count=0,
            legs_closed=0,
            engine=ENGINE_VERSION,
            underlying=args.underlying,
            notes=f"empty period: end_date <= start_date ({args.underlying})",
        )
        return report.model_dump(mode="json")

    prices = args.underlying_prices or _synthetic_prices(args.underlying, days + 1)
    if len(prices) != days + 1:
        raise ValueError(
            f"underlying_prices length {len(prices)} != days+1 {days + 1}"
        )
    # 腿默认：t0 建仓持有到期的 ATM call（expiry 覆盖整个区间）
    positions = args.positions or [
        [
            {
                "leg_type": "call",
                "strike": round(prices[0], 4),
                "expiry_offset_days": days,
                "quantity": 1,
            }
        ]
    ] + [[] for _ in range(days)]
    if len(positions) != days + 1:
        raise ValueError(f"positions length {len(positions)} != days+1 {days + 1}")

    out = run_options_backtest(prices, positions, start_date=args.start_date)
    out["strategy_name"] = args.strategy_name
    out["underlying"] = args.underlying
    out["notes"] = (
        f"daily BS mark-to-market backtest (engine {ENGINE_VERSION}): "
        f"pnl={out['total_pnl']:.2f}, dd={out['max_drawdown']}, "
        f"legs_closed={out['legs_closed']}, fee={out['fee_total']}"
    )
    out = {k: v for k, v in out.items() if k not in ("params_used", "final_cash", "final_option_value", "fee_total")}
    return OptionsBacktestReport.model_validate(out).model_dump(mode="json")


run_options_backtest_stub_tool = ToolDef(
    id="run_options_backtest_stub",
    description=(
        "Run a daily-mark-to-market options strategy backtest (engine options_v1: "
        "Black-Scholes daily re-pricing with tau decay, intrinsic settlement at expiry, "
        "per-leg commission). Input: strategy_name, underlying, start_date, end_date; "
        "optional underlying_prices + positions (legs: leg_type/strike/expiry_offset_days/"
        "quantity). Returns OptionsBacktestReport JSON with engine/net_value/"
        "max_drawdown/sharpe/total_pnl/legs_closed."
    ),
    schema=RunOptionsBacktestArgs,
    execute=run_options_backtest_execute,
)

__all__ = [
    "run_options_backtest_stub_tool",
    "RunOptionsBacktestArgs",
    "run_options_backtest_execute",
]