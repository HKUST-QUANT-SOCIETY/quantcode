"""
RiskTool Stub — 风控数据 stub，给杨欣琳的 risk 组 Agent 提供测试数据。

提供两种场景：
- normal:    所有风险指标在阈值以内
- high_risk: 风险指标超阈值

用法：
    python -m tools.risk_stub normal
    python -m tools.risk_stub high_risk
"""
from __future__ import annotations

import json
import sys
from datetime import date
from typing import Literal

# ---------------------------------------------------------------------------
# HumanGate 阈值常量
# ---------------------------------------------------------------------------

VAR_99_LIMIT = 0.05
MAX_DRAWDOWN_LIMIT = 0.15
POSITION_LIMIT_USAGE_LIMIT = 0.8


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def calc_risk_stub(scenario: Literal["normal", "high_risk"]) -> dict:
    """
    返回风控评估数据，输出结构对齐 schemas/risk-profile.schema.json。

    normal 场景：
        - 所有指标都在阈值以内

    high_risk 场景：
        - 多个指标超出阈值

    阈值为 HumanGate 常量：
        - tail_risk_var_99  > VAR_99_LIMIT               → gate triggered
        - max_drawdown      > MAX_DRAWDOWN_LIMIT          → gate triggered
        - position_limit_usage > POSITION_LIMIT_USAGE_LIMIT → gate triggered
    """
    today = date.today().isoformat()

    thresholds = {
        "VAR_99_LIMIT": VAR_99_LIMIT,
        "MAX_DRAWDOWN_LIMIT": MAX_DRAWDOWN_LIMIT,
        "POSITION_LIMIT_USAGE_LIMIT": POSITION_LIMIT_USAGE_LIMIT,
    }

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


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m tools.risk_stub <normal|high_risk>", file=sys.stderr)
        sys.exit(1)

    scenario = sys.argv[1]
    result = calc_risk_stub(scenario)  # type: ignore[arg-type]
    print(json.dumps(result, indent=2, ensure_ascii=False))
