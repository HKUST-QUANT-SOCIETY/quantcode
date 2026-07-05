"""
Rule-based router — deterministic next-step decision for the Agent.

Priority (from Plan §1.1):
  1. max_iterations_exceeded  → abort_max_iterations
  2. loop detected            → abort_loop
  3. fingerprint repeat       → abort_loop
  4. risk threshold exceeded  → human_gate
  5. task finished            → finish
  6. otherwise                → continue

Abort always wins over human_gate: a looping Agent should be stopped,
not handed to a human reviewer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .guards import detect_loop
from tools.risk_stub import (
    VAR_99_LIMIT,
    MAX_DRAWDOWN_LIMIT,
    POSITION_LIMIT_USAGE_LIMIT,
)


# ---------------------------------------------------------------------------
# Decision enum
# ---------------------------------------------------------------------------

class RouteDecision(StrEnum):
    CONTINUE               = "continue"
    HUMAN_GATE             = "human_gate"
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
      - risk_metrics           : dict | None   (output of calc_risk_stub)
      - task_status            : str | None    ("done" triggers finish)
    """

    iteration_count    = state.get("iteration_count", 0)
    tool_call_history  = state.get("tool_call_history", [])
    fingerprint_history = state.get("fingerprint_history", [])
    risk_metrics       = state.get("risk_metrics")
    task_status        = state.get("task_status")

    # ---- 1. Guards first (abort beats everything) -------------------------
    guard = detect_loop(tool_call_history, fingerprint_history, iteration_count)
    if guard.aborted:
        if guard.reason == "max_iterations_exceeded":
            return RouteResult(
                decision=RouteDecision.ABORT_MAX_ITERATIONS,
                reason=guard.reason,
                detail=guard.detail,
            )
        return RouteResult(
            decision=RouteDecision.ABORT_LOOP,
            reason=guard.reason,
            detail=guard.detail,
        )

    # ---- 2. Human gate (risk threshold check) -----------------------------
    if risk_metrics and _risk_exceeds_threshold(risk_metrics):
        return RouteResult(
            decision=RouteDecision.HUMAN_GATE,
            reason="risk_threshold_exceeded",
            detail={"risk_metrics": risk_metrics},
        )

    # ---- 3. Finish --------------------------------------------------------
    if task_status == "done":
        return RouteResult(
            decision=RouteDecision.FINISH,
            reason="task_completed",
        )

    # ---- 4. Default -------------------------------------------------------
    return RouteResult(decision=RouteDecision.CONTINUE, reason="normal")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _risk_exceeds_threshold(metrics: dict[str, Any]) -> bool:
    """Return True if any risk metric exceeds its threshold."""
    if metrics.get("tail_risk_var_99", 0) > VAR_99_LIMIT:
        return True
    if metrics.get("max_drawdown", 0) > MAX_DRAWDOWN_LIMIT:
        return True
    if metrics.get("position_limit_usage", 0) > POSITION_LIMIT_USAGE_LIMIT:
        return True
    return False
