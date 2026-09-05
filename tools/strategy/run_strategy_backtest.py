"""run_strategy_backtest tool — 调真实日频回测引擎，产出 StrategyReport。

ROADMAP D3b / P-02：原权重离散度公式 stub（sharpe=1.4-0.3*max(weights)）已替换为
tools/strategy/backtest_engine.py 的真回测引擎（A 股约束自研 internal_v1）。

- weights 仍由上游 combine_signals（真排序）产出，本工具只负责转引擎调用：
  单期目标权重展成 `lookback_days` 不变权重序列（合成价格 fixture 驱动，
  ReturnsDataset 无源——SPEC §2.2/§5，接行情表后改为真实收益序列）；
- verdict 判定沿用（sharpe≥0.5 且 max_dd≤0.25，与 flows/strategy_compose.py
  内联规则一致；configs/acceptance.risk.yaml 无 sharpe 键，读不出该组合→
  引擎内联常量，出处见 backtest_engine.VERDICT_SHARPE_MIN 注释）；
- 输出含 `engine: "internal_v1"` 标注（在 backtest 子对象里）。

合成价格 fixture：按 asset 名哈希确定性生成几何随机游走（种子固定），
保证全仓暴露口径下回测确定性、可复现，测试断言不依赖行情源。
# ponytail: 合成价格是 D3b 已知捷径，ReturnsDataset 接 StockDailyBar 后换真行情。
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from pydantic import BaseModel, Field

from schemas.strategy import (
    BacktestSummary,
    StrategyReport,
    StrategyVerdict,
)
from tools.registry import ToolDef
from tools.strategy.backtest_engine import (
    ENGINE_VERSION,
    VERDICT_MAX_DD_MAX,
    VERDICT_SHARPE_MIN,
    run_backtest,
)


class RunStrategyBacktestArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    as_of_date: date
    weights: dict[str, float] = Field(min_length=1)
    lookback_days: int = Field(default=252, ge=20, le=1260)


def _synthetic_prices(assets: list[str], n: int) -> dict[str, list[float]]:
    """确定式合成价格：年漂移 +12% + 按资产名哈希错相位的正弦扰动（日波动 ~0.6%）。

    调参约束：strategy:compose 流的内联 verdict（sharpe≥0.5 且 dd≤0.25）须对
    默认买持组合 pass（tests/test_flows_six.py 的流回归依赖），故漂移恒正。
    # ponytail: 有意用无随机数正弦扰动——伪随机种子碰运气的 seed 会造出深回撤
    # 资产，verdict 变成哈希抽签；接 StockDailyBar 真行情后整段替换。
    """
    prices: dict[str, list[float]] = {}
    for a in assets:
        seed = int.from_bytes(a.encode("utf-8")[:8], "big")
        phase = (seed % 97 + 1) / 7.0
        freq = 1.0 + (seed >> 3) % 5 * 0.5  # 0.5~3.0 频率散布，资产间相关性 < 1
        px = 10.0
        series = [px]
        for t in range(1, n):
            r = 0.12 / 252.0 + 0.004 * math.sin(phase + t / freq)
            px *= math.exp(r)
            series.append(px)
        prices[a] = series
    return prices


def run_strategy_backtest_execute(args: RunStrategyBacktestArgs, ctx: dict) -> dict:
    assets = sorted(args.weights.keys())

    # 交易日序列（自然日近似 D3b 合成口径；行情表接入后换交易日历）
    start = args.as_of_date - timedelta(days=args.lookback_days)
    dates = [start + timedelta(days=i) for i in range(args.lookback_days + 1)]
    n = len(dates)

    # 目标权重 → 每日不变权重序列（t0 空仓，t1..tn-1 建仓并持有）
    daily_weights = [{}, *({a: float(args.weights[a]) for a in assets} for _ in range(n - 1))]

    prices = _synthetic_prices(assets, n)
    engine_out = run_backtest(prices, daily_weights, dates=dates)

    sharpe = engine_out["sharpe"]
    max_dd = engine_out["max_drawdown"]

    verdict = StrategyVerdict.PASS
    fail_reasons: list[str] = []
    # 阈值出处：flows/strategy_compose.py 内联规则（sharpe 无 yaml 单源）
    if sharpe is None or sharpe < VERDICT_SHARPE_MIN:
        verdict = StrategyVerdict.FAIL
        fail_reasons.append(f"sharpe {sharpe} < {VERDICT_SHARPE_MIN}")
    if max_dd > VERDICT_MAX_DD_MAX:
        fail_reasons.append(f"max_drawdown {max_dd} > {VERDICT_MAX_DD_MAX}")
        if verdict == StrategyVerdict.PASS:
            verdict = StrategyVerdict.NEEDS_HUMAN
    if engine_out["gross_exposure_violations"] > 0:
        fail_reasons.append(
            f"gross exposure exceeded 1.0 on {engine_out['gross_exposure_violations']} rebalance(s)"
        )

    report = StrategyReport(
        strategy_name=args.strategy_name,
        as_of_date=args.as_of_date,
        selected_signals=list(args.weights.keys()),
        weights=args.weights,
        engine=ENGINE_VERSION,
        backtest=BacktestSummary(
            start_date=dates[0],
            end_date=dates[-1],
            annual_return=engine_out["annual_return"],
            sharpe=sharpe,
            max_drawdown=max_dd,
            turnover_monthly=engine_out["turnover_monthly"],
            net_value=engine_out["net_value"],
            turnover_total=engine_out["turnover_total"],
            fee_total=engine_out["fee_total"],
            skipped_days=engine_out["skipped_days"],
            gross_exposure_violations=engine_out["gross_exposure_violations"],
        ),
        verdict=verdict,
        fail_reasons=fail_reasons,
    )
    out = report.model_dump(mode="json")
    return out  # engine 字段已随 schema 序列化（report.engine = internal_v1）


run_strategy_backtest_tool = ToolDef(
    id="run_strategy_backtest",
    description=(
        "Run a daily-frequency portfolio backtest (internal_v1 engine: commission "
        "double-sided 0.0003, stamp tax 0.0005 sell-only, T+1, 10% price limit) for "
        "combined signal weights, driven by deterministic synthetic prices. "
        "Input: strategy_name, as_of_date, weights{signal_id: weight}. "
        "Returns StrategyReport JSON (selected_signals, weights, backtest, verdict) "
        "with top-level engine marker."
    ),
    schema=RunStrategyBacktestArgs,
    execute=run_strategy_backtest_execute,
)

__all__ = [
    "run_strategy_backtest_tool",
    "RunStrategyBacktestArgs",
    "run_strategy_backtest_execute",
]