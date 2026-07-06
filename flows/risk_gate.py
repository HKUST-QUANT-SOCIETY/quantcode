"""Legacy risk:gate DAG compatibility — prefer runner.risk_agent.

Fixed-node DAG is deprecated (PR #17 review). Primary path:
runner.risk_agent.build_risk_agent + registered risk tools + SKILL.md.
Interrupt/resume behavior is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runner.human_gate import (
    build_interrupt_payload,
    gate_check,
    make_gate_id,
    parse_resume_decision,
)
from runner.risk_agent import (
    HUMAN_REVIEW_NODE,
    RiskAgentState as RiskFlowState,
    build_risk_agent as build_workflow,
    finalize_output,
    human_review,
    register_risk_gate_flow,
    resume_risk_gate,
    write_pr_comment_node as write_pr_comment,
)
from schemas import ModelSpec, RiskProfile, RiskThresholds
from tools.risk.risk_tools import (
    calc_risk,
    generate_risk_profile as build_risk_profile,
    read_blackboard,
)

try:
    from langgraph.types import interrupt

    _INTERRUPT_AVAILABLE = True
except ImportError:  # pragma: no cover
    interrupt = None  # type: ignore[assignment]
    _INTERRUPT_AVAILABLE = False


def read_model_spec(state: RiskFlowState) -> dict[str, Any]:
    """Compat shim — read ModelSpec from blackboard/input_data."""
    blackboard = read_blackboard(state["input_data"])
    spec = ModelSpec(**blackboard["model_spec"])
    return {"model_spec": spec.model_dump(mode="json")}


def calc_risk_metrics(state: RiskFlowState) -> dict[str, Any]:
    """Compat shim — calculate risk metrics."""
    scenario = state["input_data"].get("scenario", "normal")
    metrics = calc_risk(state["model_spec"], scenario=scenario)
    return {"risk_metrics": metrics}


def generate_risk_profile(state: RiskFlowState) -> dict[str, Any]:
    """Compat shim — build RiskProfile artifact."""
    input_data = state["input_data"]
    profile = build_risk_profile(
        state["model_spec"],
        state["risk_metrics"],
        pr_url=input_data.get("pr_url"),
    )
    profile_data = profile.model_dump(mode="json")
    artifact_path = Path("artifacts") / "risk" / f"{profile.strategy_id}-profile.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "risk_profile": profile_data,
        "artifacts": [artifact_path.as_posix()],
    }


def check_human_gate(state: RiskFlowState) -> dict[str, Any]:
    """Compat shim — HumanGate check with interrupt/resume."""
    profile = RiskProfile(**state["risk_profile"])
    thresholds = RiskThresholds()
    check = gate_check(profile, thresholds)

    if not check["requires_human"]:
        return {"gate_check": check}

    gate_id = state.get("gate_id") or make_gate_id(state.get("thread_id", "risk"))
    if _INTERRUPT_AVAILABLE and not state.get("gate_decision"):
        resume_payload = interrupt(
            build_interrupt_payload(
                gate_id=gate_id,
                risk_profile=state["risk_profile"],
                reasons=check["reasons"],
            )
        )
        decision = parse_resume_decision(resume_payload)
    else:
        decision = state.get("gate_decision")

    return {
        "gate_check": check,
        "gate_id": gate_id,
        "gate_decision": decision,
        "human_gate_payload": build_interrupt_payload(
            gate_id=gate_id,
            risk_profile=state["risk_profile"],
            reasons=check["reasons"],
            decision=decision,
        ),
    }


__all__ = [
    "RiskFlowState",
    "HUMAN_REVIEW_NODE",
    "read_model_spec",
    "calc_risk_metrics",
    "generate_risk_profile",
    "check_human_gate",
    "human_review",
    "write_pr_comment",
    "finalize_output",
    "build_workflow",
    "register_risk_gate_flow",
    "resume_risk_gate",
]
