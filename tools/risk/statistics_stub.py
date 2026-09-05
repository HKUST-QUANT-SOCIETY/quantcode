"""
RiskTool Stub — 风控数据 stub，给 risk 组 Agent 提供测试数据。

阈值定义权归 schemas.risk_profile.RiskThresholds（PR #17），本 stub 不重复定义常量。

calc_risk_from_returns：唯一不依赖 stub 的真值函数——从真实收益率序列
（纯 python/statistics）计算指标，字段名对齐 schemas.risk_profile.RiskProfile。
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from statistics import mean, stdev
from typing import Literal

from schemas.risk_profile import RiskThresholds


def _threshold_snapshot() -> dict[str, float]:
    limits = RiskThresholds()
    return {
        "max_drawdown": limits.max_drawdown,
        "position_limit_usage": limits.position_limit_usage,
        "tail_risk_var_99": limits.tail_risk_var_99,
        "correlation_limit": limits.correlation_limit,
    }


def calc_risk_stub(scenario: Literal["normal", "high_risk"]) -> dict:
    """返回风控评估数据，输出结构对齐 RiskProfile schema。"""
    today = date.today().isoformat()
    thresholds = _threshold_snapshot()

    if scenario == "normal":
        return {
            "strategy_id": "risk-stub-demo",
            "as_of_date": today,
            "max_drawdown": 0.08,
            "position_limit": 0.45,
            "correlation_with_existing": 0.30,
            "capacity_estimate_usd": 50_000_000,
            "tail_risk_var_99": 0.025,
            "volatility": 0.12,
            "position_limit_usage": 0.45,
            "thresholds": thresholds,
        }

    if scenario == "high_risk":
        return {
            "strategy_id": "risk-stub-demo",
            "as_of_date": today,
            "max_drawdown": 0.22,
            "position_limit": 0.92,
            "correlation_with_existing": 0.70,
            "capacity_estimate_usd": 50_000_000,
            "tail_risk_var_99": 0.085,
            "volatility": 0.35,
            "position_limit_usage": 0.92,
            "thresholds": thresholds,
        }

    raise ValueError(f"Unknown scenario: {scenario!r}")


_TRADING_DAYS_PER_YEAR = 252


def _linear_quantile(sorted_values: list[float], q: float) -> float:
    """线性插值分位数（与 numpy 默认 'linear' 一致）：pos = (n-1) * q。"""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def calc_risk_from_returns(returns: list[float]) -> dict:
    """从真实收益率序列计算风控指标（纯 python/statistics，无 stub）。

    字段名对齐 schemas.risk_profile.RiskProfile / calc_risk_stub 输出：

    - tail_risk_var_99: 收益率 1% 分位数的损失幅度（正数=亏损，
      即 VaR99 = -quantile(returns, 0.01)，线性插值分位数）
    - max_drawdown: 累计净值 (1+r) 连乘后的峰值回撤（正数）
    - sharpe: mean(returns) / stdev(returns) * sqrt(252)（样本标准差，n-1）
    - volatility: stdev(returns) * sqrt(252)（日频年化）

    约束：returns 需 >= 2 个元素且均为 > -1 的简单收益率
    （<= -1 会使净值非正、累计回撤失去意义，直接拒绝而不是静默裁剪）。
    std 为 0（常数序列）时 sharpe/volatility 记 0.0，不抛 ZeroDivisionError。
    """
    if not isinstance(returns, (list, tuple)) or len(returns) < 2:
        raise ValueError("returns must be a list of at least 2 floats")
    if any(not isinstance(r, (int, float)) or isinstance(r, bool) or r <= -1 for r in returns):
        raise ValueError("returns must be numbers greater than -1 (simple returns)")

    sorted_returns = sorted(float(r) for r in returns)
    var_99 = -_linear_quantile(sorted_returns, 0.01)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for r in returns:  # 按时间原序累计净值，不能排序
        equity *= 1.0 + float(r)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)

    avg = mean([float(r) for r in returns])
    std = stdev([float(r) for r in returns])
    if std == 0:
        sharpe = 0.0
        volatility = 0.0
    else:
        sharpe = avg / std * math.sqrt(_TRADING_DAYS_PER_YEAR)
        volatility = std * math.sqrt(_TRADING_DAYS_PER_YEAR)

    return {
        "tail_risk_var_99": var_99,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "volatility": volatility,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m tools.risk.statistics_stub <normal|high_risk>", file=sys.stderr)
        sys.exit(1)

    scenario = sys.argv[1]
    result = calc_risk_stub(scenario)  # type: ignore[arg-type]
    print(json.dumps(result, indent=2, ensure_ascii=False))
