"""
RiskTool Stub — 风控数据 stub，给 risk 组 Agent 提供测试数据。

阈值定义权归 schemas.risk_profile.RiskThresholds（PR #17），本 stub 不重复定义常量。
"""
from __future__ import annotations

import json
import sys
from datetime import date
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m tools.risk.statistics_stub <normal|high_risk>", file=sys.stderr)
        sys.exit(1)

    scenario = sys.argv[1]
    result = calc_risk_stub(scenario)  # type: ignore[arg-type]
    print(json.dumps(result, indent=2, ensure_ascii=False))
