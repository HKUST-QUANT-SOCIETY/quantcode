"""
Rule-based router — deterministic next-step decision for the Agent.

Priority (from Plan §1.1):
  1. max_iterations_exceeded  → abort_max_iterations
  2. loop detected            → abort_loop  (frequency / fingerprint / errors / TF-IDF)
  3. risk threshold exceeded  → human_gate
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
from schemas.risk_profile import RiskThresholds

# 阈值定义权归 schemas.risk_profile.RiskThresholds（单一事实来源）。
_THRESHOLDS = RiskThresholds()


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
      - execution_trace        : list[dict]  (for TF-IDF + error detection)
      - risk_metrics           : dict | None (output of calc_risk)
      - task_status            : str | None  ("done" triggers finish)
    """

    iteration_count    = state.get("iteration_count", 0)
    tool_call_history  = state.get("tool_call_history", [])
    fingerprint_history = state.get("fingerprint_history", [])
    execution_trace    = state.get("execution_trace") or []
    risk_metrics       = state.get("risk_metrics")
    task_status        = state.get("task_status")
    human_review_result = state.get("human_review_result")

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
        # All other loop detections → human review (don't kill agent directly)
        return RouteResult(
            decision=RouteDecision.ABORT_LOOP,
            reason=guard.reason,
            detail=guard.detail,
        )

    # ---- 2. Risk gating ---------------------------------------------------
    # Rule-based threshold (always active), but only before a human has already
    # made a decision for this checkpoint. After approve/proceed the agent must
    # be allowed to continue without re-triggering the same gate on unchanged
    # risk_metrics; after reject/abort the human_gate routing will end safely.
    #
    # Day 5 fix: 只在 risk_profile 存在时触发（确保 generate_risk_profile 已运行），
    # 避免在 calc_risk 之后立即触发，导致 generate_risk_profile 和 check_gate 无法执行。
    # generate_risk_profile_tool 会写入 risk_profile，所以生产路径也能正常触发。
    risk_profile = state.get("risk_profile")
    if (
        risk_metrics
        and risk_profile is not None
        and _risk_exceeds_threshold(risk_metrics)
        and human_review_result not in ("proceed", "abort")
    ):
        return RouteResult(
            decision=RouteDecision.HUMAN_GATE,
            reason="risk_threshold_exceeded",
            detail={"risk_metrics": risk_metrics, "risk_profile": risk_profile},
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
    """Return True if any risk metric exceeds its RiskThresholds limit."""
    if metrics.get("tail_risk_var_99", 0) > _THRESHOLDS.tail_risk_var_99:
        return True
    if metrics.get("max_drawdown", 0) > _THRESHOLDS.max_drawdown:
        return True
    if metrics.get("position_limit", 0) > _THRESHOLDS.position_limit_usage:
        return True
    # Day 4 俞高磊：加上 correlation_with_existing 检查（杨欣琳 RiskProfile 对齐）
    # 使用 abs() — 负相关（如 -0.7）同样意味着与现有持仓高度相关，应触发人审
    if abs(metrics.get("correlation_with_existing", 0)) > _THRESHOLDS.correlation_limit:
        return True
    return False


__all__ = [
    "RouteDecision",
    "RouteResult",
    "route_next_step",
]
