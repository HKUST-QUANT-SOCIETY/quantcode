"""
Demo: AI Router vs Rule Router — side-by-side comparison.

Three scenarios from Day 3 routing demo, now with AI routing comparison.

Usage:
    python scripts/demo_ai_routing.py

Requires: STEPFUN_PLAN_API_KEY env var set.
"""
from __future__ import annotations

import os
import sys

# Ensure quantcode is on path when run as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runner.routing.router import RouteDecision, route_next_step
from runner.routing.combined_router import RouterMode, route as ai_route


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def _normal_risk():
    return {
        "tail_risk_var_99": 0.025,
        "max_drawdown": 0.08,
        "position_limit": 0.45,
        "volatility": 0.12,
        "correlation_with_existing": 0.30,
        "var_99_trend": 0.001,
        "max_drawdown_trend": 0.002,
    }


def _high_risk():
    return {
        "tail_risk_var_99": 0.085,
        "max_drawdown": 0.22,
        "position_limit": 0.92,
        "volatility": 0.35,
        "correlation_with_existing": 0.70,
        "var_99_trend": 0.02,
        "max_drawdown_trend": 0.05,
    }


SCENARIOS = {
    "normal": {
        "iteration_count": 3,
        "tool_call_history": ["fetch_data", "calc_risk_stub", "save_report"],
        "fingerprint_history": ["fp1", "fp2", "fp3"],
        "risk_metrics": _normal_risk(),
        "risk_features": _normal_risk(),
        "task_goal": "Fetch data, calculate risk, save report",
        "execution_trace": [
            {"tool": "fetch_data", "success": True, "result": "data loaded"},
            {"tool": "calc_risk_stub", "success": True, "result": "risk metrics computed"},
            {"tool": "save_report", "success": True, "result": "report saved"},
        ],
        "expected_rule": RouteDecision.FINISH,
        "expected_ai_range": [RouteDecision.FINISH, RouteDecision.CONTINUE],
    },
    "high_risk": {
        "iteration_count": 5,
        "tool_call_history": ["fetch_data", "calc_risk_stub"],
        "fingerprint_history": ["fp1", "fp2"],
        "risk_metrics": _high_risk(),
        "risk_features": _high_risk(),
        "task_goal": "Fetch data and calculate risk metrics",
        "execution_trace": [
            {"tool": "fetch_data", "success": True, "result": "data loaded"},
            {"tool": "calc_risk_stub", "success": True, "result": "high risk detected"},
        ],
        "expected_rule": RouteDecision.HUMAN_GATE,
        "expected_ai_range": [RouteDecision.HUMAN_GATE],
    },
    "loop": {
        "iteration_count": 10,
        "tool_call_history": ["retry_api"] * 5,
        "fingerprint_history": ["fp_x", "fp_x", "fp_x"],
        "risk_metrics": None,
        "risk_features": {},
        "task_goal": "Process PR #42 and generate ModelSpec",
        "execution_trace": [
            {"tool": "fetch_pr", "success": True, "result": "PR #42 diff"},
            {"tool": "extract_metadata", "success": True, "result": {"author": "alice"}},
            {"tool": "validate_schema", "success": False, "error": "missing author field"},
            {"tool": "extract_metadata", "success": True, "result": {"author": "alice"}},
            {"tool": "validate_schema", "success": False, "error": "missing author field"},
            {"tool": "extract_metadata", "success": True, "result": {"author": "alice"}},
            {"tool": "validate_schema", "success": False, "error": "missing author field"},
            {"tool": "extract_metadata", "success": True, "result": {"author": "alice"}},
            {"tool": "validate_schema", "success": False, "error": "missing author field"},
            {"tool": "extract_metadata", "success": True, "result": {"author": "alice"}},
        ],
        "expected_rule": RouteDecision.ABORT_LOOP,
        "expected_ai_range": [RouteDecision.HUMAN_GATE],
    },
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    has_key = bool(os.environ.get("STEPFUN_PLAN_API_KEY"))
    if not has_key:
        print("⚠️  STEPFUN_PLAN_API_KEY not set — AI routing will use fallback\n")

    print("=" * 80)
    print("  AI Router vs Rule Router — Side-by-Side Comparison")
    print("=" * 80)
    print()

    for name, state in SCENARIOS.items():
        print(f"--- Scenario: {name} ---")

        # Rule routing
        rule_result = route_next_step(state)
        rule_ok = (
            rule_result.decision == state["expected_rule"]
            or rule_result.decision in state.get("expected_ai_range", [])
        )

        # AI routing
        ai_result = ai_route(state, mode=RouterMode.AI_WITH_FALLBACK)

        print(f"  Rule router:   decision={rule_result.decision:<25} reason={rule_result.reason}")
        print(f"  AI router:     decision={ai_result.decision:<25} reason={ai_result.reason}")
        if ai_result.detail.get("analysis"):
            analysis = str(ai_result.detail["analysis"])[:120]
            print(f"                 analysis: {analysis}")
        if ai_result.detail.get("ai_fallback"):
            print(f"                 ⚠️  fallback: {str(ai_result.detail['ai_fallback'])[:100]}")

        # Comparison
        match = rule_result.decision == ai_result.decision
        rule_str = rule_result.decision.value
        ai_str = ai_result.decision.value
        if match:
            print(f"  ✅ Both agree: {rule_str}")
        else:
            print(f"  🔀 Diverge: rule={rule_str} vs ai={ai_str}")
        print()


if __name__ == "__main__":
    main()
