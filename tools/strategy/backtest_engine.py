"""backtest_engine — 纯 python+numpy 日频组合回测引擎（ROADMAP D3b / P-02）。

A 股约束自研（不引 vectorbt）：T+1 / 涨跌停 / 双边费用语义可控、可手算对照。
# ponytail: 逐日循环 O(D*A)；日频全 A 股长窗口跑不动时再评估换 vectorbt
#（numba 向量化），本函数输入输出契约不变即可替换。

输入（与 weights 日期对齐，len == len(weights)，prices[a][0] 为期初收盘）：
    prices  : dict[asset, list[float]]
    weights : list[dict[asset, float]]，t 日末目标权重；t=0 忽略（期初全现金，
              首次调仓发生在 t=1 收盘）。每天给全量目标组合（未列出的旧持仓卖出）。
    dates   : list[date]（可选；缺省用 2026-01-01 起的自然日占位）

规则（configs/backtest.yaml，缺键回退代码默认）：
    - 费用：佣金 commission_rate 双边 + 印花税 stamp_tax 仅卖出，按成交额计
    - T+1：今日买入今日不可卖（卖出腿 day_bought==t 拒绝，次日调仓自然成交）
    - 涨跌停：|px[t]/px[t-1]-1| > limit_pct 的腿跳过并记 skipped_days，旧仓保留
    - 现金：买入受可用现金约束（不加杠杆）；Σw>1 记 gross_exposure 违规一次

输出：BacktestSummary 兼容 dict（扩展可选字段见 schemas/strategy.py）＋
     net_value / turnover_total / fee_total / skipped_days / gross_exposure_violations。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np

ENGINE_VERSION = "internal_v1"

# configs/backtest.yaml 的代码默认兜底（数值同源）
DEFAULT_FEES = {
    "commission_rate": 0.0003,  # 佣金，双边
    "stamp_tax": 0.0005,        # 印花税，仅卖出
    "limit_pct": 0.10,          # 涨跌停带宽；T+1 无参数（硬规则）
}

# verdict 阈值出处：与 flows/strategy_compose.py 内联规则一致（工具层同款）。
# configs/acceptance.risk.yaml 只有 risk-gate 语义的 max_drawdown(0.15) 且无
# sharpe 键——读不出本验收组合，故内联并注释（ROADMAP D3b：sharpe≥0.5 且 dd≤0.25）。
VERDICT_SHARPE_MIN = 0.5
VERDICT_MAX_DD_MAX = 0.25


def load_fees() -> dict[str, float]:
    """configs/backtest.yaml 优先，缺文件/缺键回退代码默认（对齐 config_loader 约定）。"""
    try:
        from runner.config_loader import load_yaml

        cfg = load_yaml("backtest")
    except Exception:  # pragma: no cover — loader 缺失时兜底
        cfg = {}
    fees = dict(DEFAULT_FEES)
    for k in fees:
        if k in cfg:
            fees[k] = float(cfg[k])
    return fees


def _limit_hit(prev_close: float, price: float, limit_pct: float) -> bool:
    if not prev_close or prev_close <= 0:
        return False
    return abs(price / prev_close - 1.0) > limit_pct + 1e-12


def run_backtest(
    prices: dict[str, list[float]],
    weights: list[dict[str, float]],
    dates: list[date] | None = None,
    fees: dict[str, float] | None = None,
) -> dict[str, Any]:
    f = {**DEFAULT_FEES, **(fees or load_fees())}
    n = len(weights)
    if n == 0:
        raise ValueError("weights must be non-empty")
    assets = sorted(prices.keys())
    for a in assets:
        if len(prices[a]) != n:
            raise ValueError(f"prices[{a}] length {len(prices[a])} != {n}")
    for t in range(n):
        for a in weights[t]:
            if a not in prices:
                raise ValueError(f"weights day {t} references unknown asset {a!r}")

    if dates is None:
        dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(n)]
    ds = [str(d) for d in dates]

    px = {a: np.asarray(prices[a], dtype=float) for a in assets}
    ret1: dict[str, np.ndarray] = {}
    for a in assets:
        r = np.zeros(n)
        r[1:] = px[a][1:] / px[a][:-1] - 1.0
        ret1[a] = r

    cash = 1.0
    held: dict[str, float] = {}       # 昨仓市值（今日开盘前口径）
    day_bought: dict[str, int] = {}   # T+1：标的最近买入日
    fee_total = 0.0
    turnover_total = 0.0              # 单边成交额 Σ(买+卖)
    skipped_days: list[str] = []
    gross_violations = 0

    nav = np.empty(n)
    nav[0] = 1.0
    final_weights: dict[str, float] = {}

    for t in range(1, n):
        # 1) 逐日盯市（昨仓按今日收益增值）
        for a in held:
            held[a] *= 1.0 + float(ret1[a][t])
        eq = cash + sum(held.values())
        eps = eq * 1e-12

        target = weights[t]
        if sum(v for v in target.values() if v > 0) > 1.0 + 1e-9:
            gross_violations += 1

        # 2) 卖出腿（先卖后买，释放现金）
        for a in sorted(set(held) | set(target)):
            want = eq * max(float(target.get(a, 0.0)), 0.0)
            have = held.get(a, 0.0)
            if want >= have - eps:
                continue
            if day_bought.get(a) == t:
                continue  # T+1：今日买入今日不可卖，次日调仓自然成交
            if _limit_hit(px[a][t - 1], px[a][t], f["limit_pct"]):
                skipped_days.append(f"{ds[t]}:{a}")  # 跌停：旧仓保留
                continue
            sell = have - want
            fee_s = sell * (f["commission_rate"] + f["stamp_tax"])
            cash += sell - fee_s
            fee_total += fee_s
            turnover_total += sell
            if want <= eps:
                del held[a]
                day_bought.pop(a, None)
            else:
                held[a] = want

        # 3) 买入腿（受可用现金约束，不加杠杆）
        for a in sorted(target):
            w = float(target[a])
            if w <= 0.0:
                continue
            want = eq * w
            have = held.get(a, 0.0)
            if want <= have + eps:
                continue
            if _limit_hit(px[a][t - 1], px[a][t], f["limit_pct"]):
                skipped_days.append(f"{ds[t]}:{a}")  # 涨停：买不进
                continue
            budget = max(cash, 0.0)
            buy = min(want - have, budget / (1.0 + f["commission_rate"]))
            if buy <= eps:
                continue
            fee_b = buy * f["commission_rate"]
            cash -= buy + fee_b
            fee_total += fee_b
            turnover_total += buy
            held[a] = have + buy
            day_bought[a] = t

        nav[t] = cash + sum(held.values())

    final_weights = {
        a: round(v / nav[-1], 6) if nav[-1] > 0 else 0.0 for a, v in held.items()
    }

    # --- 指标 ---
    if n > 1:
        daily_ret = np.diff(nav) / nav[:-1]
        if len(daily_ret) >= 2:
            std = float(daily_ret.std(ddof=1))
            sharpe: float | None = (
                round(float(daily_ret.mean()) / std * float(np.sqrt(252.0)), 4)
                if std > 1e-12
                else None
            )
        else:
            sharpe = None
        annual_return = round(float((nav[-1] / nav[0]) ** (252.0 / (n - 1)) - 1.0), 4)
        peak = np.maximum.accumulate(nav)
        max_drawdown = round(float((1.0 - nav / peak).max()), 4)
        months = (n - 1) / 21.0  # 21 交易日/月
        turnover_monthly = round((turnover_total / 2.0) / months, 4) if months > 0 else 0.0
    else:
        sharpe = None
        annual_return = 0.0
        max_drawdown = 0.0
        turnover_monthly = 0.0

    return {
        "engine": ENGINE_VERSION,
        "start_date": ds[0],
        "end_date": ds[-1],
        "annual_return": annual_return,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "turnover_monthly": turnover_monthly,
        "net_value": [round(float(v), 10) for v in nav],
        "turnover_total": round(float(turnover_total), 10),
        "fee_total": round(float(fee_total), 10),
        "skipped_days": skipped_days,
        "gross_exposure_violations": gross_violations,
        "final_weights": final_weights,
        "fees_used": dict(f),
    }