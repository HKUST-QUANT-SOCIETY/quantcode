"""期权日频回测引擎 options_v1（纯 python，复用 build_vol_surface 的 BS 定价）。

对齐 strategy/backtest_engine.py 的逐日循环 + 手算对账风格，规则简化为期权特性：
- 输入：underlying_prices（标的收盘序列）、positions（每日期权腿：
  {leg_type: call|put, strike, expiry_offset_days, quantity}），
  每期给全量腿集合（与上期不同的旧腿视为平仓，与 weights 语义一致）
- 盯市：option value 用 BS（from tools.options.build_vol_surface import _bs_price），
  到期（tau<=0）按内在价值结算后从后续组合中移除；theta 不另算——BS 逐日重定
  价本身内含时间价值衰减（tau 每日 -1 天），等价日衰减 theta*dt
- 现金：期初 initial_capital，建仓付 option 价 × |quantity| × multiplier + commission，
  期权多头不付保证金（空头杠杆不在 v1 范围，quantity<0 时按负持仓盯市）
- 费用：每腿建仓一次性 commission（configs/options_backtest.yaml）

输出：OptionsBacktestReport 兼容 dict + net_value / daily_pnl / legs_closed /
engine: "options_v1"。
# ponytail: 逐腿逐日 O(D*L) 纯循环；期权多腿×长窗口跑不动时再向量化。
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np

from tools.options.build_vol_surface import _bs_price

ENGINE_VERSION = "options_v1"
MULTIPLIER = 100  # 单张合约乘数（CME 口径）

DEFAULT_PARAMS = {
    "initial_capital": 100000.0,
    "commission": 1.0,          # 每腿建仓一次性费用（绝对额）
    "risk_free_rate": 0.0,
    "implied_vol": 0.20,
}


def load_params() -> dict[str, float]:
    """configs/options_backtest.yaml 优先，缺文件/缺键回退代码默认。"""
    try:
        from runner.config_loader import load_yaml

        cfg = load_yaml("options_backtest")
    except Exception:  # pragma: no cover — loader 缺失时兜底
        cfg = {}
    params = dict(DEFAULT_PARAMS)
    for k in params:
        if k in cfg:
            params[k] = float(cfg[k])
    return params


def _validate_leg(leg: dict, t: int) -> None:
    if not isinstance(leg, dict):
        raise ValueError(f"positions day {t}: each leg must be an object")
    lt = str(leg.get("leg_type", "")).lower()
    if lt not in ("call", "put"):
        raise ValueError(f"positions day {t}: leg_type must be call|put, got {leg.get('leg_type')!r}")
    try:
        strike = float(leg.get("strike", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"positions day {t}: strike must be a finite number") from exc
    if not math.isfinite(strike) or strike <= 0:
        raise ValueError(f"positions day {t}: strike must be > 0")
    try:
        quantity = float(leg.get("quantity", 0))
        expiry_offset = float(leg.get("expiry_offset_days"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"positions day {t}: quantity and expiry_offset_days must be finite numbers"
        ) from exc
    if not math.isfinite(quantity) or not quantity.is_integer() or int(quantity) == 0:
        raise ValueError(f"positions day {t}: quantity must be non-zero")
    if not math.isfinite(expiry_offset) or not expiry_offset.is_integer() or expiry_offset < 0:
        raise ValueError(
            f"positions day {t}: expiry_offset_days must be a non-negative integer"
        )


def run_options_backtest(
    underlying_prices: list[float],
    positions: list[dict],
    start_date: date | None = None,
    params: dict[str, float] | None = None,
) -> dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or load_params())}
    n = len(underlying_prices)
    if n == 0:
        raise ValueError("underlying_prices must be non-empty")
    if len(positions) != n:
        raise ValueError(f"positions length {len(positions)} != prices length {n}")
    if not math.isfinite(float(underlying_prices[0])) or underlying_prices[0] <= 0:
        raise ValueError("underlying_prices[0] must be > 0")

    for t in range(1, n):  # t0 建仓不盯当日价格变动，仅校验可定价
        if not math.isfinite(float(underlying_prices[t])) or underlying_prices[t] <= 0:
            raise ValueError(f"underlying_prices[{t}] must be > 0")
    for t, legs in enumerate(positions):
        if not isinstance(legs, list):
            raise ValueError(f"positions day {t}: legs must be a list")
        for leg in legs:
            _validate_leg(leg, t)

    if start_date is None:
        start_date = date(2026, 1, 1)
    dates = [start_date + timedelta(days=i) for i in range(n)]

    # 活跃腿状态：到期日（日序号）、strike、type、quantity
    active: list[dict] = []
    cash = float(p["initial_capital"])
    fee_total = 0.0
    legs_closed = 0
    nav = np.empty(n)
    value = np.zeros(n)  # 期权市值合计

    for t in range(n):
        # 1) 到期结算：tau<=0 按内在价值入现金，腿移除
        expired = [leg for leg in active if leg["expiry_t"] <= t]
        for leg in expired:
            s = underlying_prices[min(t, n - 1)]
            intrinsic = max(s - leg["strike"], 0.0) if leg["is_call"] else max(leg["strike"] - s, 0.0)
            cash += intrinsic * MULTIPLIER * leg["quantity"]
            legs_closed += 1
        if expired:
            active = [leg for leg in active if leg["expiry_t"] > t]

        # 2) 换仓：positions[t] 全量目标（与上期不同的旧腿平仓按现价回收入现金）
        target = positions[t]
        kept: list[dict] = []
        for leg in active:
            match = next(
                (
                    g
                    for g in target
                    if str(g["leg_type"]).lower() == leg["type"]
                    and float(g["strike"]) == leg["strike"]
                    and int(g["expiry_offset_days"]) == leg["expiry_t"] - t
                ),
                None,
            )
            if match is None:
                tau = max((leg["expiry_t"] - t) / 365.0, 0.0)
                price = _bs_price(
                    underlying_prices[t], leg["strike"], tau, float(p["risk_free_rate"]),
                    float(p["implied_vol"]), leg["is_call"],
                )
                cash += price * MULTIPLIER * leg["quantity"]
                cash -= float(p["commission"])
                fee_total += float(p["commission"])
                legs_closed += 1
            else:
                kept.append(leg)
        active = kept
        for leg in target:
            dup = any(
                str(leg["leg_type"]).lower() == k["type"]
                and float(leg["strike"]) == k["strike"]
                and int(leg["expiry_offset_days"]) == k["expiry_t"] - t
                for k in active
            )
            if dup:
                continue
            tau = max(int(leg["expiry_offset_days"]) / 365.0, 0.0)
            price = _bs_price(
                underlying_prices[t], float(leg["strike"]), tau, float(p["risk_free_rate"]),
                float(p["implied_vol"]), str(leg["leg_type"]).lower() == "call",
            )
            cost = price * MULTIPLIER * float(leg["quantity"])
            if cost > cash:  # 不加杠杆：现金不足腿不成交
                continue
            cash -= cost + float(p["commission"])
            fee_total += float(p["commission"])
            active.append(
                {
                    "type": str(leg["leg_type"]).lower(),
                    "is_call": str(leg["leg_type"]).lower() == "call",
                    "strike": float(leg["strike"]),
                    "expiry_t": t + int(leg["expiry_offset_days"]),
                    "quantity": int(leg["quantity"]),
                }
            )

        # 3) 盯市：BS 逐日重定价（内含 theta/365 时间衰减），tau<=0 按内在价值
        value_t = 0.0
        for leg in active:
            tau = max((leg["expiry_t"] - t) / 365.0, 0.0)
            pv = _bs_price(
                underlying_prices[t], leg["strike"], tau, float(p["risk_free_rate"]),
                float(p["implied_vol"]), leg["is_call"],
            ) if tau > 0 else (
                max(underlying_prices[t] - leg["strike"], 0.0)
                if leg["is_call"]
                else max(leg["strike"] - underlying_prices[t], 0.0)
            )
            value_t += pv * MULTIPLIER * leg["quantity"]
        value[t] = value_t
        nav[t] = cash + value_t

    nav = np.asarray(nav, dtype=float)
    total_pnl = float(nav[-1] - p["initial_capital"])

    # --- 指标（对齐 strategy 引擎口径） ---
    daily_pnl = np.diff(np.concatenate(([p["initial_capital"]], nav)))
    daily_ret = np.diff(nav) / np.where(nav[:-1] == 0.0, 1e-12, nav[:-1])
    sharpe: float | None = None
    if n > 2:
        std = float(daily_ret.std(ddof=1))
        sharpe = round(float(daily_ret.mean()) / std * float(np.sqrt(252.0)), 4) if std > 1e-12 else None
    peak = np.maximum.accumulate(nav)
    max_drawdown = round(float((1.0 - nav / peak).max()), 4)

    return {
        "engine": ENGINE_VERSION,
        "strategy_name": "",
        "period_start": dates[0].isoformat(),
        "period_end": dates[-1].isoformat(),
        "total_pnl": round(total_pnl, 10),
        "max_drawdown": min(max_drawdown, 1.0),
        "sharpe": sharpe,
        "trade_count": n - 1,
        "net_value": [round(float(v) / float(p["initial_capital"]), 10) for v in nav],
        "daily_pnl": [round(float(v), 10) for v in daily_pnl],
        "legs_closed": legs_closed,
        "fee_total": round(float(fee_total), 10),
        "underlying": None,
        "notes": None,
        "final_cash": round(float(cash), 10),
        "final_option_value": round(float(value[-1]), 10),
        "params_used": {k: float(p[k]) for k in DEFAULT_PARAMS},
    }
