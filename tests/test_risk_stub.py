"""Tests for tools.risk_stub — RiskTool stub data provider."""
from __future__ import annotations

import pytest

from tools.risk_stub import (
    MAX_DRAWDOWN_LIMIT,
    POSITION_LIMIT_USAGE_LIMIT,
    VAR_99_LIMIT,
    calc_risk_stub,
)


class TestRiskStubNormal:
    """normal 场景：所有指标在阈值以内，should_trigger_gate = False"""

    def test_returns_all_required_fields(self):
        result = calc_risk_stub("normal")
        required = [
            "strategy_id",
            "as_of_date",
            "max_drawdown",
            "position_limit",
            "correlation_with_existing",
            "capacity_estimate_usd",
            "tail_risk_var_99",
            "volatility",
            "position_limit_usage",
            "should_trigger_gate",
            "thresholds",
        ]
        for field in required:
            assert field in result, f"缺少字段: {field}"

    def test_should_trigger_gate_is_false(self):
        result = calc_risk_stub("normal")
        assert result["should_trigger_gate"] is False

    def test_all_metrics_within_limits(self):
        result = calc_risk_stub("normal")
        assert result["tail_risk_var_99"] <= VAR_99_LIMIT
        assert result["max_drawdown"] <= MAX_DRAWDOWN_LIMIT
        assert result["position_limit_usage"] <= POSITION_LIMIT_USAGE_LIMIT

    def test_thresholds_match_constants(self):
        result = calc_risk_stub("normal")
        t = result["thresholds"]
        assert t["VAR_99_LIMIT"] == VAR_99_LIMIT
        assert t["MAX_DRAWDOWN_LIMIT"] == MAX_DRAWDOWN_LIMIT
        assert t["POSITION_LIMIT_USAGE_LIMIT"] == POSITION_LIMIT_USAGE_LIMIT


class TestRiskStubHighRisk:
    """high_risk 场景：多个指标超阈值，should_trigger_gate = True"""

    def test_returns_all_required_fields(self):
        result = calc_risk_stub("high_risk")
        required = [
            "strategy_id",
            "as_of_date",
            "max_drawdown",
            "position_limit",
            "correlation_with_existing",
            "capacity_estimate_usd",
            "tail_risk_var_99",
            "volatility",
            "position_limit_usage",
            "should_trigger_gate",
            "thresholds",
        ]
        for field in required:
            assert field in result, f"缺少字段: {field}"

    def test_should_trigger_gate_is_true(self):
        result = calc_risk_stub("high_risk")
        assert result["should_trigger_gate"] is True

    def test_at_least_one_metric_exceeds_limit(self):
        result = calc_risk_stub("high_risk")
        over_var = result["tail_risk_var_99"] > VAR_99_LIMIT
        over_dd = result["max_drawdown"] > MAX_DRAWDOWN_LIMIT
        over_pos = result["position_limit_usage"] > POSITION_LIMIT_USAGE_LIMIT
        assert over_var or over_dd or over_pos, (
            "high_risk 场景下至少一个指标应超出阈值"
        )


class TestRiskStubError:
    """错误处理"""

    def test_unknown_scenario_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            calc_risk_stub("unknown")  # type: ignore[arg-type]

    def test_unknown_scenario_raises_valueerror_empty(self):
        with pytest.raises(ValueError):
            calc_risk_stub("")  # type: ignore[arg-type]
