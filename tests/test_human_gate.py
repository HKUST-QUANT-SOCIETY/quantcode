"""Tests for HumanGate schema and should_interrupt."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from runner.human_gate import should_interrupt
from schemas.human_gate import (
    HumanGate,
    HumanGateDecision,
    HumanGateDecisionAction,
    HumanGateStatus,
)
from schemas.risk_profile import RiskProfile, RiskThresholds
from tools.risk.statistics_stub import calc_risk_stub


def _profile_from_stub(scenario: str) -> RiskProfile:
    raw = calc_risk_stub(scenario)  # type: ignore[arg-type]
    for extra in ("volatility", "position_limit_usage", "should_trigger_gate"):
        raw.pop(extra, None)
    return RiskProfile(**raw)


def _gate(status: HumanGateStatus, **decision_kwargs) -> HumanGate:
    decision = None
    if decision_kwargs:
        decision = HumanGateDecision(**decision_kwargs)
    return HumanGate(gate_id="hg_test_1", status=status, decision=decision)


def test_human_gate_schema_valid():
    gate = _gate(
        HumanGateStatus.APPROVED,
        action=HumanGateDecisionAction.APPROVE,
        decided_by="risk-lead",
        reason="within policy",
    )
    assert gate.status == HumanGateStatus.APPROVED
    assert gate.decision is not None
    assert gate.decision.action == HumanGateDecisionAction.APPROVE


def test_human_gate_rejects_empty_gate_id():
    with pytest.raises(ValidationError):
        HumanGate(gate_id="", status=HumanGateStatus.PENDING)


def test_should_interrupt_normal_profile():
    profile = _profile_from_stub("normal")
    thresholds = RiskThresholds()
    assert should_interrupt(profile, thresholds) is False
    assert should_interrupt(profile, thresholds, gate=_gate(HumanGateStatus.PENDING)) is False


def test_should_interrupt_high_risk_profile():
    profile = _profile_from_stub("high_risk")
    thresholds = RiskThresholds()
    assert should_interrupt(profile, thresholds) is True


def test_should_interrupt_max_drawdown_only():
    profile = RiskProfile(
        strategy_id="demo",
        as_of_date="2024-03-15",
        max_drawdown=0.20,
        position_limit=0.10,
        correlation_with_existing=0.20,
        capacity_estimate_usd=1_000_000,
        tail_risk_var_99=0.02,
    )
    assert should_interrupt(profile, RiskThresholds()) is True


def test_should_interrupt_var_only():
    profile = RiskProfile(
        strategy_id="demo",
        as_of_date="2024-03-15",
        max_drawdown=0.10,
        position_limit=0.10,
        correlation_with_existing=0.20,
        capacity_estimate_usd=1_000_000,
        tail_risk_var_99=0.08,
    )
    assert should_interrupt(profile, RiskThresholds()) is True


def test_should_interrupt_position_limit_usage_only():
    profile = RiskProfile(
        strategy_id="demo",
        as_of_date="2024-03-15",
        max_drawdown=0.10,
        position_limit=0.85,
        correlation_with_existing=0.20,
        capacity_estimate_usd=1_000_000,
        tail_risk_var_99=0.02,
    )
    assert should_interrupt(profile, RiskThresholds()) is True


def test_should_interrupt_correlation_only():
    profile = RiskProfile(
        strategy_id="demo",
        as_of_date="2024-03-15",
        max_drawdown=0.10,
        position_limit=0.10,
        correlation_with_existing=0.75,
        capacity_estimate_usd=1_000_000,
        tail_risk_var_99=0.02,
    )
    assert should_interrupt(profile, RiskThresholds()) is True


def test_should_not_interrupt_when_gate_approved():
    profile = _profile_from_stub("high_risk")
    gate = _gate(
        HumanGateStatus.APPROVED,
        action=HumanGateDecisionAction.APPROVE,
        decided_by="risk-lead",
    )
    assert should_interrupt(profile, RiskThresholds(), gate=gate) is False


def test_should_not_interrupt_when_gate_rejected():
    profile = _profile_from_stub("high_risk")
    gate = _gate(
        HumanGateStatus.REJECTED,
        action=HumanGateDecisionAction.REJECT,
        decided_by="risk-lead",
        reason="policy violation",
    )
    assert should_interrupt(profile, RiskThresholds(), gate=gate) is False
