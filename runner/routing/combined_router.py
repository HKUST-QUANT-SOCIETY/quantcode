"""
Combined Router — unified routing that combines hard constraints, LLM trace
analysis, and ML gate classification.

Usage:
    from runner.routing.combined_router import route, RouterMode

    result = route(state)                                  # ai_with_fallback (default)
    result = route(state, mode=RouterMode.RULE)            # deterministic only
    result = route(state, mode=RouterMode.AI_ONLY)         # LLM + ML, no fallback

The router is designed to be used as a LangGraph conditional edge function:
    app.add_conditional_edges("agent_node", route, {...})

Model persistence:
    Pass a pre-trained GateClassifier via ``gate_classifier=clf``, or set
    ``GATE_MODEL_PATH`` env var to auto-load a saved model at startup.
"""
from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from .router import RouteDecision, RouteResult
from .guards import MAX_ITERATIONS

RouterFunc = Callable[[dict[str, Any]], RouteResult]

# Default path for auto-loaded / saved GateClassifier model.
DEFAULT_GATE_MODEL_PATH = Path(".quantcode/gate_classifier_model.json")


def _resolve_gate_classifier(
    gate_classifier: Any,
) -> Any | None:
    """Resolve the GateClassifier to use.

    Priority:
      1. Explicit classifier passed by caller (already trained)
      2. GATE_MODEL_PATH env var → load from file
      3. DEFAULT_GATE_MODEL_PATH exists → load from file
      4. None (ML gate skipped)
    """
    import json as _json

    if gate_classifier is not None:
        return gate_classifier

    # Check env var first……
    from .gate_classifier import GateClassifier
    env_path = os.environ.get("GATE_MODEL_PATH", "")
    if env_path:
        p = Path(env_path)
        if p.exists():
            clf = GateClassifier()
            clf.load(p)
            return clf

    # …then default path
    default = _repo_root() / DEFAULT_GATE_MODEL_PATH
    if default.exists():
        clf = GateClassifier()
        clf.load(default)
        return clf

    return None


def _repo_root() -> Path:
    """Walk up from this file to find repo root."""
    here = Path(__file__).resolve().parent
    for _ in range(6):
        if (here / ".git").exists() or (here / "pyproject.toml").exists():
            return here
        here = here.parent
    return Path.cwd()


# ---------------------------------------------------------------------------
# Router mode
# ---------------------------------------------------------------------------

class RouterMode(StrEnum):
    RULE = "rule"                    # Deterministic guards only
    AI_ONLY = "ai"                   # LLM + ML, no fallback
    AI_WITH_FALLBACK = "ai_with_fallback"  # LLM + ML, fallback to rule on error


# ---------------------------------------------------------------------------
# Combined router
# ---------------------------------------------------------------------------

def route(
    state: dict[str, Any],
    *,
    mode: RouterMode = RouterMode.AI_WITH_FALLBACK,
    gate_classifier: Any = None,       # GateClassifier instance (lazy import)
    task_goal: str = "",
    api_key: str | None = None,
) -> RouteResult:
    """
    Decide the next step for the Agent.

    Priority (from plan):
      1. iteration > MAX_ITERATIONS → abort_max_iterations (hard cap, no AI)
      2. LLM trace analysis → suspects_loop → human_gate(workflow_failure)
                              → is_complete  → finish
      3. ML gate classifier → P(gate) > 0.5 → human_gate(risk_gate_uncertain)
      4. Otherwise → continue

    Parameters:
      state: Agent state dict with:
        - iteration_count: int
        - execution_trace: list[dict]  (tool call history with results)
        - risk_features: dict          (raw risk metrics for GateClassifier)
        - task_goal: str               (natural language task description)
      mode: routing strategy
      gate_classifier: GateClassifier instance (lazy-loaded if None)
      task_goal: can be overridden here or read from state
      api_key: StepFun API key for LLM routing

    Returns RouteResult.
    """
    iteration_count = state.get("iteration_count", 0)

    # ---- 1. Hard constraint (always enforced, regardless of mode) ----
    if iteration_count > MAX_ITERATIONS:
        return RouteResult(
            decision=RouteDecision.ABORT_MAX_ITERATIONS,
            reason="max_iterations_exceeded",
            detail={"iteration_count": iteration_count, "max": MAX_ITERATIONS},
        )

    # ---- Rule-only mode: delegate to deterministic router ----
    if mode == RouterMode.RULE:
        from .router import route_next_step
        return route_next_step(state)

    # ---- AI mode: LLM trace + ML gate ----
    risk_features = state.get("risk_features") or state.get("risk_metrics")
    execution_trace = state.get("execution_trace", [])
    goal = task_goal or state.get("task_goal", "")

    try:
        # 2. LLM trace analysis — health check first
        from .ai_router import ai_analyze_trace
        trace_result = ai_analyze_trace(
            execution_trace,
            task_goal=goal,
            api_key=api_key,
        )

        if trace_result.fallback and mode == RouterMode.AI_WITH_FALLBACK:
            # LLM failed — fall back to deterministic routing
            from .router import route_next_step
            rule_result = route_next_step(state)
            rule_result.detail["ai_fallback"] = trace_result.analysis
            return rule_result

        if trace_result.suspects_loop:
            return RouteResult(
                decision=RouteDecision.HUMAN_GATE,
                reason="workflow_failure",
                detail={
                    "trigger": "workflow_failure",
                    "analysis": trace_result.analysis,
                    "source": "ai_analyze_trace",
                },
            )

        if trace_result.is_complete:
            return RouteResult(
                decision=RouteDecision.FINISH,
                reason="task_completed",
                detail={"analysis": trace_result.analysis},
            )

        # 3. ML gate classifier — safety check
        if risk_features:
            clf = _resolve_gate_classifier(gate_classifier)
            if clf is not None:
                prob, gate_reason = clf.predict(risk_features)
                if prob > 0.5:
                    return RouteResult(
                        decision=RouteDecision.HUMAN_GATE,
                        reason="risk_gate_uncertain",
                        detail={
                            "trigger": "risk_gate_uncertain",
                            "score": prob,
                            "reason": gate_reason,
                            "source": "gate_classifier",
                        },
                    )

    except Exception as exc:
        if mode == RouterMode.AI_WITH_FALLBACK:
            from .router import route_next_step
            rule_result = route_next_step(state)
            rule_result.detail["ai_fallback"] = str(exc)
            return rule_result
        raise

    # ---- 4. Default ----
    return RouteResult(decision=RouteDecision.CONTINUE, reason="normal")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_router(
    mode: RouterMode = RouterMode.AI_WITH_FALLBACK,
    **kwargs: Any,
) -> RouterFunc:
    """
    Factory returning a router function with pre-configured mode.

        rule_router = get_router(RouterMode.RULE)
        ai_router   = get_router(RouterMode.AI_WITH_FALLBACK)
    """
    def _route(state: dict[str, Any]) -> RouteResult:
        return route(state, mode=mode, **kwargs)
    return _route
