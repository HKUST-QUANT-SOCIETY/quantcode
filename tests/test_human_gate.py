"""Tests for HumanGate schema (Pattern 5: Human-in-the-Loop Gate)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schemas.human_gate import (
    HumanGate,
    HumanGateDecision,
    HumanGateDecisionAction,
    HumanGateStatus,
    HumanGateTrigger,
    NotifyChannel,
    RiskMetrics,
)

VALID_SESSION = "S0123456789abcdef"
VALID_CREATED_AT = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


def _valid_human_gate(**overrides) -> HumanGate:
    data = {
        "gate_id": "hg_T1.2_1751443200",
        "task_id": "T1.2",
        "session_id": VALID_SESSION,
        "pr_url": "https://github.com/hkust-quant-society/quantcode/pull/42",
        "head_sha": "abcdef1234567890",
        "status": HumanGateStatus.PENDING,
        "trigger": HumanGateTrigger.MAX_DRAWDOWN_EXCEEDED,
        "trigger_reason": "Observed drawdown 18% exceeds 15% threshold",
        "risk_thresholds": {"max_drawdown": 0.15, "position_limit": 0.1},
        "observed_values": {"max_drawdown": 0.18},
        "timeout_minutes": 60,
        "notify_channels": [NotifyChannel.SLACK, NotifyChannel.GITHUB_PR_COMMENT],
        "required_approvers": ["risk-lead"],
        "created_at": VALID_CREATED_AT,
    }
    data.update(overrides)
    return HumanGate(**data)


def test_human_gate_valid():
    gate = _valid_human_gate()
    assert gate.gate_id == "hg_T1.2_1751443200"
    assert gate.task_id == "T1.2"
    assert gate.status == HumanGateStatus.PENDING
    assert gate.decision is None
    assert gate.risk_thresholds.max_drawdown == 0.15


def test_human_gate_rejects_invalid_task_id():
    with pytest.raises(ValidationError, match="task_id"):
        _valid_human_gate(task_id="INVALID")


def test_human_gate_rejects_max_drawdown_out_of_range():
    with pytest.raises(ValidationError, match="max_drawdown"):
        _valid_human_gate(risk_thresholds=RiskMetrics(max_drawdown=1.5))


def test_human_gate_pending_allows_decision_none():
    gate = _valid_human_gate(status=HumanGateStatus.PENDING, decision=None)
    assert gate.decision is None


def test_human_gate_approved_requires_decision():
    with pytest.raises(ValidationError, match="requires decision"):
        _valid_human_gate(status=HumanGateStatus.APPROVED, decision=None)


def test_human_gate_approved_with_decision_valid():
    gate = _valid_human_gate(
        status=HumanGateStatus.APPROVED,
        decision=HumanGateDecision(
            action=HumanGateDecisionAction.APPROVE,
            decided_by="risk-lead",
            decided_at=VALID_CREATED_AT,
            reason="Drawdown spike is transient; within policy after review",
        ),
    )
    assert gate.decision is not None
    assert gate.decision.action == HumanGateDecisionAction.APPROVE
