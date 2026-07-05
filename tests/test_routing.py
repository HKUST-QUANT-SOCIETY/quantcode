"""Tests for runner.routing.router — rule-based routing decisions."""
from __future__ import annotations

import pytest

from runner.routing.router import (
    RouteDecision,
    RouteResult,
    route_next_step,
)
from runner.routing.guards import MAX_ITERATIONS
from tools.risk_stub import calc_risk_stub


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
    def test_high_risk_triggers_gate(self):
        r = route_next_step(_state(risk_metrics=calc_risk_stub("high_risk")))
        assert r.decision == RouteDecision.HUMAN_GATE
        assert r.reason == "risk_threshold_exceeded"


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
