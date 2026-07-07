"""
Demo: routing and guards in action.

Three scenarios to verify the execution control layer works end-to-end:
  1. normal     → task completes normally, route = finish
  2. high_risk  → risk metrics exceed thresholds, route = human_gate
  3. loop       → same tool called repeatedly, route = abort_loop

Run:
    python scripts/demo_routing_guards.py
"""
from __future__ import annotations

from runner.routing.router import RouteDecision, route_next_step
from tools.risk_stub import calc_risk_stub


def _label(r: RouteDecision) -> str:
    return r.value.ljust(22)


# ---------------------------------------------------------------------------
# Scenario 1: normal
# ---------------------------------------------------------------------------

def demo_normal() -> None:
    state = {
        "iteration_count": 3,
        "tool_call_history": ["fetch_data", "calc_risk_stub", "save_report"],
        "fingerprint_history": ["fp_a", "fp_b", "fp_c"],
        "risk_metrics": calc_risk_stub("normal"),
        "task_status": "done",
    }
    result = route_next_step(state)
    print(f"[normal]     route={_label(result.decision)} reason={result.reason}")


# ---------------------------------------------------------------------------
# Scenario 2: high_risk → human_gate
# ---------------------------------------------------------------------------

def demo_high_risk() -> None:
    state = {
        "iteration_count": 5,
        "tool_call_history": ["fetch_data", "calc_risk_stub"],
        "fingerprint_history": ["fp_a", "fp_b"],
        "risk_metrics": calc_risk_stub("high_risk"),
        "task_status": None,
    }
    result = route_next_step(state)
    print(f"[high_risk]  route={_label(result.decision)} reason={result.reason}")


# ---------------------------------------------------------------------------
# Scenario 3: loop → abort_loop
# ---------------------------------------------------------------------------

def demo_loop() -> None:
    state = {
        "iteration_count": 10,
        "tool_call_history": ["retry_api"] * 5,       # 5 consecutive = loop
        "fingerprint_history": ["fp_x"] * 3,           # 3 repeats  = loop
        "risk_metrics": None,
        "task_status": None,
    }
    result = route_next_step(state)
    print(f"[loop]       route={_label(result.decision)} reason={result.reason}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    demo_normal()
    demo_high_risk()
    demo_loop()
    print()
