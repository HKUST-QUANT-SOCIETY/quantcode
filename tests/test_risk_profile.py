"""Tests for risk group RiskProfile schema."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas import RiskGateVerdict, RiskProfile, RiskThresholds
from tools.risk.statistics_stub import calc_risk_stub


def _profile_from_stub(scenario: str) -> RiskProfile:
    raw = calc_risk_stub(scenario)  # type: ignore[arg-type]
    for extra in ("volatility", "position_limit_usage", "thresholds"):
        raw.pop(extra, None)
    return RiskProfile(**raw)


def test_risk_profile_accepts_normal_stub_data():
    profile = _profile_from_stub("normal")

    assert profile.strategy_id == "risk-stub-demo"
    assert profile.max_drawdown == 0.08
    assert profile.tail_risk_var_99 == 0.025
    assert profile.evaluate_verdict() == RiskGateVerdict.PASS
    assert profile.breached_thresholds() == []


def test_risk_profile_accepts_high_risk_stub_data():
    profile = _profile_from_stub("high_risk")

    assert profile.max_drawdown == 0.22
    assert profile.tail_risk_var_99 == 0.085
    assert profile.evaluate_verdict() == RiskGateVerdict.NEEDS_HUMAN
    assert "max_drawdown" in profile.breached_thresholds()
    assert "tail_risk_var_99" in profile.breached_thresholds()


def test_risk_thresholds_defaults():
    thresholds = RiskThresholds()

    assert thresholds.max_drawdown == 0.15
    assert thresholds.position_limit_usage == 0.8
    assert thresholds.tail_risk_var_99 == 0.05
    assert thresholds.correlation_limit == 0.6


def test_risk_profile_rejects_invalid_max_drawdown():
    with pytest.raises(ValidationError, match="max_drawdown"):
        RiskProfile(
            strategy_id="demo",
            as_of_date="2024-03-15",
            max_drawdown=1.5,
            position_limit=0.45,
            correlation_with_existing=0.30,
            capacity_estimate_usd=50_000_000,
            tail_risk_var_99=0.025,
        )


def test_risk_profile_rejects_invalid_correlation():
    with pytest.raises(ValidationError, match="correlation_with_existing"):
        RiskProfile(
            strategy_id="demo",
            as_of_date="2024-03-15",
            max_drawdown=0.08,
            position_limit=0.45,
            correlation_with_existing=1.5,
            capacity_estimate_usd=50_000_000,
            tail_risk_var_99=0.025,
        )
