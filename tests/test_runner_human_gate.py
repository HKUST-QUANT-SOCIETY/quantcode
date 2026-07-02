"""Tests for runner.human_gate.should_interrupt."""
from __future__ import annotations

from datetime import datetime, timezone

from schemas.human_gate import (
    HumanGate,
    HumanGateStatus,
    HumanGateTrigger,
    NotifyChannel,
    RiskMetrics,
)

from runner.human_gate import should_interrupt

VALID_CREATED_AT = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


def _gate_config(**overrides) -> HumanGate:
    data = {
        "gate_id": "hg_T1_1",
        "task_id": "T1",
        "status": HumanGateStatus.PENDING,
        "trigger": HumanGateTrigger.MAX_DRAWDOWN_EXCEEDED,
        "risk_thresholds": {"max_drawdown": 0.15},
        "timeout_minutes": 60,
        "notify_channels": [NotifyChannel.SLACK],
        "required_approvers": ["risk-lead"],
        "created_at": VALID_CREATED_AT,
    }
    data.update(overrides)
    return HumanGate(**data)


def test_should_interrupt_when_max_drawdown_exceeded():
    state = {"max_drawdown": 0.18, "position_limit": 0.10}
    assert should_interrupt(state, _gate_config()) is True


def test_should_not_interrupt_when_within_threshold():
    state = {"max_drawdown": 0.12, "position_limit": 0.10}
    assert should_interrupt(state, _gate_config()) is False


def test_should_not_interrupt_when_gate_resolved():
    state = {"max_drawdown": 0.18}
    gate = _gate_config(
        status=HumanGateStatus.APPROVED,
        decision={
            "action": "approve",
            "decided_by": "risk-lead",
            "decided_at": VALID_CREATED_AT,
            "reason": "within policy after review",
        },
    )
    assert should_interrupt(state, gate) is False


def test_should_interrupt_missing_risk_profile():
    gate = _gate_config(trigger=HumanGateTrigger.MISSING_RISK_PROFILE)
    assert should_interrupt({}, gate) is True
    assert should_interrupt({"risk_profile": {"max_drawdown": 0.1}}, gate) is False


def test_should_interrupt_manual_request():
    gate = _gate_config(
        trigger=HumanGateTrigger.MANUAL_REQUEST,
        risk_thresholds=RiskMetrics(),
    )
    assert should_interrupt({"manual_request": True}, gate) is True
    assert should_interrupt({"manual_request": False}, gate) is False
