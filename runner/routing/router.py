"""
Rule-based router — deterministic next-step decision for the Agent.

Priority (from Plan §1.1):
  1. max_iterations_exceeded  → abort_max_iterations
  2. loop detected            → abort_loop  (frequency / fingerprint / errors / TF-IDF)
  3. risk threshold exceeded  → domain verdict (no gate)
  4. task finished            → finish
  5. otherwise                → continue

Abort always wins over human_gate: a looping Agent should be stopped,
not handed to a human reviewer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .guards import detect_loop
# ---------------------------------------------------------------------------
# Decision enum
# ---------------------------------------------------------------------------

class RouteDecision(StrEnum):
    CONTINUE               = "continue"
    ABORT_LOOP             = "abort_loop"
    ABORT_MAX_ITERATIONS   = "abort_max_iterations"
    FINISH                 = "finish"


# ---------------------------------------------------------------------------
# Result wrapper
# ---------------------------------------------------------------------------

@dataclass
class RouteResult:
    decision: RouteDecision
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_next_step(state: dict[str, Any]) -> RouteResult:
    """
    Decide what the Agent should do next based on `state`.

    Expected keys in state:
      - iteration_count        : int
      - tool_call_history      : list[str]
      - fingerprint_history    : list[str]
      - execution_trace        : list[dict]  (for TF-IDF + error detection)
      - risk_metrics           : dict | None (output of calc_risk)
      - task_status            : str | None  ("done" triggers finish)
    """

    iteration_count    = state.get("iteration_count", 0)
    tool_call_history  = state.get("tool_call_history", [])
    fingerprint_history = state.get("fingerprint_history", [])
    execution_trace    = state.get("execution_trace") or []
    task_status        = state.get("task_status")

    # ---- 1. Guards (loop detection — always rule-based) ------------------
    guard = detect_loop(
        tool_call_history,
        fingerprint_history,
        iteration_count,
        execution_trace=execution_trace,
    )
    if guard.aborted:
        if guard.reason == "max_iterations_exceeded":
            return RouteResult(
                decision=RouteDecision.ABORT_MAX_ITERATIONS,
                reason=guard.reason,
                detail=guard.detail,
            )
        # All other loop detections stop the run; loops are runtime failures,
        # never a HumanGate.
        return RouteResult(
            decision=RouteDecision.ABORT_LOOP,
            reason=guard.reason,
            detail=guard.detail,
        )

    # ---- 2. Risk verdict --------------------------------------------------
    # Risk metrics are domain output only. They never create a HumanGate; the
    # owning risk component or report decides pass, fail, or warning.

    # ---- 3. Finish --------------------------------------------------------
    if task_status == "done":
        return RouteResult(
            decision=RouteDecision.FINISH,
            reason="task_completed",
        )

    # ---- 4. Default -------------------------------------------------------
    return RouteResult(decision=RouteDecision.CONTINUE, reason="normal")


__all__ = [
    "RouteDecision",
    "RouteResult",
    "route_next_step",
]
