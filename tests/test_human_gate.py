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
    for extra in ("volatility", "position_limit_usage", "thresholds"):
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


def test_make_gate_id_uses_uuid_suffix():
    from runner.human_gate import make_gate_id

    gate_id = make_gate_id("risk:risk:gate:demo")
    assert gate_id.startswith("hg_risk_risk_gate_demo_")
    assert len(gate_id.split("_")[-1]) == 12


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


# ---------------------------------------------------------------------------
# Day 7: decision normalization & OpenCode-facing helpers
# ---------------------------------------------------------------------------


class TestNormalizeExternalDecision:
    """normalize_external_decision — 将所有变体映射为 approve/reject。"""

    def test_approve_maps_to_approve(self):
        from runner.human_gate import normalize_external_decision
        assert normalize_external_decision("approve") == "approve"

    def test_proceed_maps_to_approve(self):
        from runner.human_gate import normalize_external_decision
        assert normalize_external_decision("proceed") == "approve"

    def test_reject_maps_to_reject(self):
        from runner.human_gate import normalize_external_decision
        assert normalize_external_decision("reject") == "reject"

    def test_abort_maps_to_reject(self):
        from runner.human_gate import normalize_external_decision
        assert normalize_external_decision("abort") == "reject"

    def test_unknown_maps_to_reject_fail_closed(self):
        from runner.human_gate import normalize_external_decision
        assert normalize_external_decision("garbage") == "reject"

    def test_none_maps_to_reject(self):
        from runner.human_gate import normalize_external_decision
        assert normalize_external_decision(None) == "reject"  # type: ignore[arg-type]

    def test_case_insensitive(self):
        from runner.human_gate import normalize_external_decision
        assert normalize_external_decision("APPROVE") == "approve"
        assert normalize_external_decision("Approve") == "approve"


class TestToReactResumePayload:
    """to_react_resume_payload — OpenCode approve/reject → ReAct proceed/abort。"""

    def test_approve_to_proceed(self):
        from runner.human_gate import to_react_resume_payload
        assert to_react_resume_payload("approve") == {"decision": "proceed"}

    def test_reject_to_abort(self):
        from runner.human_gate import to_react_resume_payload
        assert to_react_resume_payload("reject") == {"decision": "abort"}

    def test_proceed_passthrough(self):
        from runner.human_gate import to_react_resume_payload
        assert to_react_resume_payload("proceed") == {"decision": "proceed"}

    def test_abort_passthrough(self):
        from runner.human_gate import to_react_resume_payload
        assert to_react_resume_payload("abort") == {"decision": "abort"}

    def test_garbage_falls_back_to_abort(self):
        from runner.human_gate import to_react_resume_payload
        assert to_react_resume_payload("???") == {"decision": "abort"}


class TestExtractInterruptPayload:
    """extract_interrupt_payload — 从 state 提取 pending interrupt。"""

    def test_no_interrupt_returns_none(self):
        from runner.human_gate import extract_interrupt_payload
        assert extract_interrupt_payload({}) is None

    def test_empty_interrupt_list_returns_none(self):
        from runner.human_gate import extract_interrupt_payload
        assert extract_interrupt_payload({"__interrupt__": []}) is None

    def test_extracts_dict_value(self):
        from runner.human_gate import extract_interrupt_payload
        payload = {"gate_id": "hg_1", "message": "wait"}
        from unittest.mock import Mock
        interrupt = Mock()
        interrupt.value = payload
        state = {"__interrupt__": [interrupt]}
        assert extract_interrupt_payload(state) == payload

    def test_extracts_raw_value(self):
        from runner.human_gate import extract_interrupt_payload
        state = {"__interrupt__": [{"gate_id": "hg_2", "message": "wait"}]}
        result = extract_interrupt_payload(state)
        assert result is not None
        assert result["gate_id"] == "hg_2"


class TestFormatWaitingForHuman:
    """format_waiting_for_human — MCP run_agent waiting_for_human 输出。"""

    def test_basic_shape(self):
        from runner.human_gate import format_waiting_for_human
        result = format_waiting_for_human(
            thread_id="tid-1",
            interrupt_payload={
                "gate_id": "hg_abc",
                "message": "⏸️ wait",
                "reasons": ["var > limit"],
                "risk_profile": {"var_99": 0.08},
            },
        )
        assert result["status"] == "waiting_for_human"
        assert result["thread_id"] == "tid-1"
        gate = result["gate"]
        assert gate["kind"] == "human_gate"
        assert gate["gate_id"] == "hg_abc"
        assert "var > limit" in gate["reasons"]
        assert gate["decision_schema"]["allowed"] == ["approve", "reject"]
        assert gate["decision_schema"]["default"] == "reject"

    def test_risk_metrics_passed_through(self):
        from runner.human_gate import format_waiting_for_human
        result = format_waiting_for_human(
            thread_id="t2",
            interrupt_payload={
                "gate_id": "g",
                "message": "m",
                "risk_profile": {"var_99": 0.12, "max_drawdown": 0.35},
                "reasons": ["high dd"],
            },
        )
        assert result["gate"]["risk_metrics"]["var_99"] == 0.12


class TestGateCheck:
    """gate_check 返回 requires_human 与 reasons。"""

    def test_normal_no_human(self):
        from runner.human_gate import gate_check
        profile = _profile_from_stub("normal")
        result = gate_check(profile, RiskThresholds())
        assert result["requires_human"] is False
        assert result["reasons"] == []

    def test_high_risk_requires_human(self):
        from runner.human_gate import gate_check
        profile = _profile_from_stub("high_risk")
        result = gate_check(profile, RiskThresholds())
        assert result["requires_human"] is True
        assert len(result["reasons"]) > 0


class TestBuildInterruptPayload:
    """build_interrupt_payload — 构造 LangGraph interrupt payload。"""

    def test_returns_dict(self):
        from runner.human_gate import build_interrupt_payload
        payload = build_interrupt_payload(
            gate_id="g1",
            risk_profile={"var": 0.05},
            reasons=["r1"],
        )
        assert isinstance(payload, dict)
        assert payload["gate_id"] == "g1"
        assert "⏸️" in payload["message"]

    def test_custom_message(self):
        from runner.human_gate import build_interrupt_payload
        payload = build_interrupt_payload(
            gate_id="g2",
            risk_profile={},
            reasons=[],
            message="custom wait",
        )
        assert payload["message"] == "custom wait"


class TestParseResumeDecision:
    """parse_resume_decision — 从 resume payload 解析 decision。"""

    def test_dict(self):
        from runner.human_gate import parse_resume_decision
        assert parse_resume_decision({"decision": "proceed"}) == "proceed"

    def test_string_returns_none(self):
        from runner.human_gate import parse_resume_decision
        assert parse_resume_decision("proceed") is None

    def test_none_returns_none(self):
        from runner.human_gate import parse_resume_decision
        assert parse_resume_decision(None) is None

    def test_empty_dict_returns_none(self):
        from runner.human_gate import parse_resume_decision
        assert parse_resume_decision({}) is None
