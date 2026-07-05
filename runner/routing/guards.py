"""
Execution guards — loop detection + max-iteration limit.

Two layers of loop detection:
  1. Tool-call frequency (sliding window)
  2. Repeated state fingerprint (Agent making no progress)

Plus a hard iteration cap.  Used by router.py to decide whether to abort.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fingerprint import compute_state_fingerprint

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

WINDOW_SIZE = 10               # sliding window for tool-call history
MAX_SAME_TOOL_IN_WINDOW = 8    # same tool ≤7 times in the window (>=8 triggers abort)
MAX_CONSECUTIVE_SAME_TOOL = 5  # same tool ≤4 consecutive calls
MAX_FINGERPRINT_REPEAT = 3     # same fingerprint ≤2 repeats before abort
MAX_ITERATIONS = 100           # hard iteration cap


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    """Unified guard check outcome."""
    aborted: bool = False
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_max_iterations(
    iteration_count: int,
    max_iterations: int = MAX_ITERATIONS,
) -> GuardResult:
    """Return an abort result if `iteration_count` exceeds the cap."""
    if iteration_count > max_iterations:
        return GuardResult(
            aborted=True,
            reason="max_iterations_exceeded",
            detail={
                "iteration_count": iteration_count,
                "max_iterations": max_iterations,
            },
        )
    return GuardResult()


def detect_loop_by_tool_frequency(
    tool_call_history: list[str],
    window_size: int = WINDOW_SIZE,
    max_same_in_window: int = MAX_SAME_TOOL_IN_WINDOW,
    max_consecutive: int = MAX_CONSECUTIVE_SAME_TOOL,
) -> GuardResult:
    """
    Check whether the same tool appears too often in the recent history.

    Two triggers (either → abort):
      - Within the last *window_size* calls, the same tool appears
        ≥ *max_same_in_window* times.
      - The same tool has been called ≥ *max_consecutive* times in a row.
    """
    if not tool_call_history:
        return GuardResult()

    # --- consecutive check ------------------------------------------------
    recent = tool_call_history[-max_consecutive:]
    if len(recent) >= max_consecutive and len(set(recent)) == 1:
        tool = recent[0]
        return GuardResult(
            aborted=True,
            reason="loop_detected",
            detail={
                "trigger": "consecutive_same_tool",
                "tool": tool,
                "consecutive_count": len(recent),
                "threshold": max_consecutive,
            },
        )

    # --- sliding-window check --------------------------------------------
    window = tool_call_history[-window_size:]
    if len(window) >= window_size:
        counts: dict[str, int] = {}
        for t in window:
            counts[t] = counts.get(t, 0) + 1
        max_count = max(counts.values())
        if max_count >= max_same_in_window:
            culprit = [t for t, c in counts.items() if c == max_count][0]
            return GuardResult(
                aborted=True,
                reason="loop_detected",
                detail={
                    "trigger": "frequency_in_window",
                    "tool": culprit,
                    "count": max_count,
                    "window_size": window_size,
                    "threshold": max_same_in_window,
                },
            )

    return GuardResult()


def detect_loop_by_fingerprint(
    fingerprint_history: list[str],
    max_repeat: int = MAX_FINGERPRINT_REPEAT,
) -> GuardResult:
    """
    Check whether the same state fingerprint appears too many times
    consecutively, indicating the Agent isn't making progress.
    """
    if len(fingerprint_history) < max_repeat:
        return GuardResult()

    last_n = fingerprint_history[-max_repeat:]
    if len(set(last_n)) == 1:
        return GuardResult(
            aborted=True,
            reason="loop_detected",
            detail={
                "trigger": "repeated_state_fingerprint",
                "fingerprint": last_n[0],
                "repeat_count": len(last_n),
                "threshold": max_repeat,
            },
        )

    return GuardResult()


def detect_loop(
    tool_call_history: list[str],
    fingerprint_history: list[str],
    iteration_count: int,
) -> GuardResult:
    """
    Composite guard: run all three checks and return the *first* abort.

    Priority:
      1. max_iterations_exceeded  (hard cap)
      2. tool-frequency loop       (consecutive or window)
      3. fingerprint repeat loop   (stale state)
    """
    result = check_max_iterations(iteration_count)
    if result.aborted:
        return result

    result = detect_loop_by_tool_frequency(tool_call_history)
    if result.aborted:
        return result

    result = detect_loop_by_fingerprint(fingerprint_history)
    if result.aborted:
        return result

    return GuardResult()
