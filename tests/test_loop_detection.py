"""Tests for runner.routing.guards — loop detection + max-iteration limit."""
from __future__ import annotations

import pytest

from runner.routing.guards import (
    MAX_CONSECUTIVE_SAME_TOOL,
    MAX_FINGERPRINT_REPEAT,
    MAX_ITERATIONS,
    MAX_SAME_TOOL_IN_WINDOW,
    WINDOW_SIZE,
    GuardResult,
    check_max_iterations,
    detect_loop,
    detect_loop_by_fingerprint,
    detect_loop_by_tool_frequency,
)


# ===========================================================================
# check_max_iterations
# ===========================================================================

class TestMaxIterations:
    def test_exceeded(self):
        r = check_max_iterations(MAX_ITERATIONS + 1)
        assert r.aborted is True
        assert r.reason == "max_iterations_exceeded"

    def test_at_boundary_not_exceeded(self):
        r = check_max_iterations(MAX_ITERATIONS)
        assert r.aborted is False

    def test_under_limit(self):
        r = check_max_iterations(5)
        assert r.aborted is False

    def test_custom_limit(self):
        r = check_max_iterations(11, max_iterations=10)
        assert r.aborted is True
        assert r.detail["max_iterations"] == 10


# ===========================================================================
# detect_loop_by_tool_frequency — consecutive
# ===========================================================================

class TestConsecutiveSameTool:
    def test_triggers_at_threshold(self):
        history = ["a"] * MAX_CONSECUTIVE_SAME_TOOL
        r = detect_loop_by_tool_frequency(history)
        assert r.aborted is True
        assert r.detail["trigger"] == "consecutive_same_tool"

    def test_no_trigger_below_threshold(self):
        history = ["a"] * (MAX_CONSECUTIVE_SAME_TOOL - 1)
        r = detect_loop_by_tool_frequency(history)
        assert r.aborted is False

    def test_only_looks_at_tail(self):
        """Consecutive check only cares about the most recent calls."""
        history = ["x", "y", "z"] + ["a"] * MAX_CONSECUTIVE_SAME_TOOL
        r = detect_loop_by_tool_frequency(history)
        assert r.aborted is True  # tail of 5 'a's triggers

    def test_interleaved_does_not_trigger(self):
        """Alternating A/B should not fire the consecutive guard."""
        history = ["a", "b"] * 10
        r = detect_loop_by_tool_frequency(history)
        # It might or might not trigger via frequency_in_window, but
        # consecutive should NOT be the trigger.
        if r.aborted:
            assert r.detail.get("trigger") != "consecutive_same_tool"


# ===========================================================================
# detect_loop_by_tool_frequency — sliding window
# ===========================================================================

class TestWindowFrequency:
    def test_triggers_when_same_tool_dominates_window(self):
        """8× 'a' + 2× 'b' in a 10-call window → trigger."""
        history = (["a"] * MAX_SAME_TOOL_IN_WINDOW) + (["b"] * (WINDOW_SIZE - MAX_SAME_TOOL_IN_WINDOW))
        r = detect_loop_by_tool_frequency(history)
        assert r.aborted is True
        assert r.detail["trigger"] == "frequency_in_window"

    def test_no_trigger_when_window_too_small(self):
        """Window not yet full — no frequency check."""
        history = ["a"] * (WINDOW_SIZE - 1)
        r = detect_loop_by_tool_frequency(history)
        # Fewer than WINDOW_SIZE calls → window check not applied
        if r.aborted:
            assert r.detail.get("trigger") != "frequency_in_window"

    def test_normal_varied_sequence_ok(self):
        """6 different tools in 10 calls should not trigger."""
        history = ["a", "b", "c", "d", "e", "f", "a", "b", "c", "a"]
        r = detect_loop_by_tool_frequency(history)
        assert r.aborted is False


# ===========================================================================
# detect_loop_by_fingerprint
# ===========================================================================

class TestFingerprintRepeat:
    def test_triggers_at_threshold(self):
        fp = "abc123"
        history = [fp] * MAX_FINGERPRINT_REPEAT
        r = detect_loop_by_fingerprint(history)
        assert r.aborted is True
        assert r.detail["trigger"] == "repeated_state_fingerprint"

    def test_no_trigger_below_threshold(self):
        fp = "abc123"
        history = [fp] * (MAX_FINGERPRINT_REPEAT - 1)
        r = detect_loop_by_fingerprint(history)
        assert r.aborted is False

    def test_same_count_different_values_ok(self):
        """Three different fingerprints → not a repeat."""
        history = ["aaa", "bbb", "ccc"]
        r = detect_loop_by_fingerprint(history)
        assert r.aborted is False

    def test_repeat_buried_in_history_no_trigger(self):
        """Old repeats don't matter; only the tail counts."""
        history = ["x", "x", "x", "y", "z", "w"]
        r = detect_loop_by_fingerprint(history)
        assert r.aborted is False

    def test_empty_history(self):
        r = detect_loop_by_fingerprint([])
        assert r.aborted is False


# ===========================================================================
# detect_loop — composite
# ===========================================================================

class TestDetectLoopComposite:
    def test_max_iterations_first(self):
        """max_iterations_exceeded should take priority."""
        r = detect_loop(
            tool_call_history=[],
            fingerprint_history=[],
            iteration_count=MAX_ITERATIONS + 1,
        )
        assert r.aborted is True
        assert r.reason == "max_iterations_exceeded"

    def test_consecutive_tool_second(self):
        r = detect_loop(
            tool_call_history=["a"] * MAX_CONSECUTIVE_SAME_TOOL,
            fingerprint_history=[],
            iteration_count=5,
        )
        assert r.aborted is True
        assert r.detail["trigger"] == "consecutive_same_tool"

    def test_no_issue_all_clear(self):
        r = detect_loop(
            tool_call_history=["a", "b", "c", "d", "e"],
            fingerprint_history=["fp1", "fp2", "fp3"],
            iteration_count=5,
        )
        assert r.aborted is False


# ===========================================================================
# GuardResult
# ===========================================================================

class TestGuardResult:
    def test_default_is_clean(self):
        r = GuardResult()
        assert r.aborted is False
        assert r.reason == ""
        assert r.detail == {}

    def test_detail_preserved(self):
        r = GuardResult(aborted=True, reason="loop_detected", detail={"tool": "x"})
        assert r.detail["tool"] == "x"
