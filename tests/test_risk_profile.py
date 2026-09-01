"""Tests for risk group RiskProfile schema."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas import RiskGateVerdict, RiskProfile, RiskThresholds

FIXTURES = Path(__file__).parent / "fixtures"


def test_risk_profile_from_normal_fixture():
    data = json.loads((FIXTURES / "risk_metrics_normal.json").read_text())
    profile = RiskProfile.model_validate(data)
    assert profile.max_drawdown == 0.08
    assert profile.evaluate_verdict() == RiskGateVerdict.PASS
    assert profile.breached_thresholds() == []


def test_risk_profile_from_breach_fixture():
    data = json.loads((FIXTURES / "risk_metrics_breach.json").read_text())
    profile = RiskProfile.model_validate(data)
    assert profile.max_drawdown == 0.22
    # v0.2 收窄（G2-A8）：越限 → verdict=fail（评估结论），不再 needs_human
    assert profile.evaluate_verdict() == RiskGateVerdict.FAIL
    assert profile.evaluate_verdict() == "fail"
    assert "max_drawdown" in profile.breached_thresholds()
    assert "tail_risk_var_99" in profile.breached_thresholds()


def test_risk_thresholds_defaults():
    limits = RiskThresholds()
    assert limits.max_drawdown == 0.15
    assert limits.position_limit_usage == 0.8


def test_risk_profile_rejects_invalid_drawdown():
    with pytest.raises(ValidationError, match="max_drawdown"):
        RiskProfile(
            strategy_id="demo",
            as_of_date="2024-03-15",
            max_drawdown=1.5,
            position_limit=0.45,
            correlation_with_existing=0.3,
            capacity_estimate_usd=1_000_000,
        )


def test_risk_profile_rejects_extra_fields():
    data = json.loads((FIXTURES / "risk_metrics_normal.json").read_text())
    data["volatility"] = 0.12
    with pytest.raises(ValidationError):
        RiskProfile.model_validate(data)
