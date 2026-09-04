"""Tests for runner.routing.router — rule-based routing decisions."""
from __future__ import annotations

# import pytest

from runner.routing.router import (
    RouteDecision,
    RouteResult,
    route_next_step,
)
from runner.routing.guards import MAX_ITERATIONS
from tools.risk.statistics_stub import calc_risk_stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(**overrides):
    base: dict = {
        "iteration_count": 1,
        "tool_call_history": [],
        "fingerprint_history": [],
        "risk_metrics": None,
        "task_status": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Continue
# ---------------------------------------------------------------------------

class TestRouteContinue:
    def test_normal_state(self):
        r = route_next_step(_state())
        assert r.decision == RouteDecision.CONTINUE

    def test_with_risk_normal(self):
        """Normal risk metrics should NOT trigger human_gate."""
        r = route_next_step(_state(risk_metrics=calc_risk_stub("normal")))
        assert r.decision == RouteDecision.CONTINUE


# ---------------------------------------------------------------------------
# Abort — max iterations
# ---------------------------------------------------------------------------

class TestRouteAbortMaxIterations:
    def test_exceeded(self):
        r = route_next_step(_state(iteration_count=MAX_ITERATIONS + 1))
        assert r.decision == RouteDecision.ABORT_MAX_ITERATIONS
        assert r.reason == "max_iterations_exceeded"


# ---------------------------------------------------------------------------
# Abort — loop
# ---------------------------------------------------------------------------

class TestRouteAbortLoop:
    def test_consecutive_same_tool(self):
        r = route_next_step(_state(
            tool_call_history=["a"] * 5,
            iteration_count=5,
        ))
        assert r.decision == RouteDecision.ABORT_LOOP
        assert r.reason == "loop_detected"

    def test_fingerprint_repeat(self):
        r = route_next_step(_state(
            fingerprint_history=["fp"] * 3,
            iteration_count=10,
        ))
        assert r.decision == RouteDecision.ABORT_LOOP


# ---------------------------------------------------------------------------
# Human gate
# ---------------------------------------------------------------------------

class TestRouteHumanGate:
    def test_high_risk_is_domain_verdict_not_gate(self):
        """v5: 风险越限是领域结果，不触发普通 HumanGate。"""
        r = route_next_step(_state(
            risk_metrics=calc_risk_stub("high_risk"),
            risk_profile={"scenario": "high_risk", "decision": "pending"},
        ))
        assert r.decision == RouteDecision.CONTINUE
        assert r.reason == "normal"

    def test_high_risk_without_profile_continues(self):
        """Day 5 fix: risk_metrics 超阈值但 risk_profile 未生成时，应 CONTINUE 让 generate_risk_profile 执行。"""
        r = route_next_step(_state(risk_metrics=calc_risk_stub("high_risk")))
        assert r.decision == RouteDecision.CONTINUE

    def test_approved_high_risk_does_not_retrigger_gate(self):
        """Approve/proceed 后，同一份 risk_metrics 不应反复触发 human_gate。"""
        r = route_next_step(_state(
            risk_metrics=calc_risk_stub("high_risk"),
            risk_profile={"scenario": "high_risk", "decision": "approved"},
            human_review_result="proceed",
        ))
        assert r.decision == RouteDecision.CONTINUE

    def test_rejected_high_risk_does_not_retrigger_gate(self):
        """Reject/abort 后也不应反复触发 human_gate；下游 human_gate routing 会安全结束。"""
        r = route_next_step(_state(
            risk_metrics=calc_risk_stub("high_risk"),
            risk_profile={"scenario": "high_risk", "decision": "rejected"},
            human_review_result="abort",
        ))
        assert r.decision == RouteDecision.CONTINUE


# ---------------------------------------------------------------------------
# Finish
# ---------------------------------------------------------------------------

class TestRouteFinish:
    def test_task_done(self):
        r = route_next_step(_state(task_status="done"))
        assert r.decision == RouteDecision.FINISH


# ---------------------------------------------------------------------------
# Priority: abort > human_gate
# ---------------------------------------------------------------------------

class TestAbortPriorityOverHumanGate:
    def test_loop_beats_high_risk(self):
        """A looping Agent should abort, not enter human_gate."""
        r = route_next_step(_state(
            tool_call_history=["a"] * 5,
            iteration_count=5,
            risk_metrics=calc_risk_stub("high_risk"),
        ))
        assert r.decision == RouteDecision.ABORT_LOOP

    def test_max_iterations_beats_high_risk(self):
        r = route_next_step(_state(
            iteration_count=MAX_ITERATIONS + 1,
            risk_metrics=calc_risk_stub("high_risk"),
        ))
        assert r.decision == RouteDecision.ABORT_MAX_ITERATIONS


# ---------------------------------------------------------------------------
# RouteResult
# ---------------------------------------------------------------------------

class TestRouteResult:
    def test_defaults(self):
        r = RouteResult(decision=RouteDecision.CONTINUE)
        assert r.decision == RouteDecision.CONTINUE
        assert r.reason == ""
        assert r.detail == {}
