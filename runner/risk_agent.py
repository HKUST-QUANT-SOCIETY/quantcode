"""Risk gate orchestrator — tool-based path with LangGraph interrupt/resume.

Primary entry for risk:gate (PR #17). Tools are registered in tools/risk/_register.py
and filtered by .opencode/groups/risk/tool_allowlist.yaml.

CI / GitHub Actions 使用本模块的确定性 scripted pipeline（保留 interrupt/resume）。
OpenCode ReAct 路径使用 runner.agent_engine.AgentRunner(group="risk") + 本 SKILL.md；
HumanGate interrupt 仍由本模块的 LangGraph 图承载，待 AgentRunner 接入 route_gate。
"""
from __future__ import annotations

import json
import operator
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, TypedDict

from runner.acceptance import AcceptanceResult, run_acceptance as run_acceptance_checks
from runner.human_gate import (
    build_interrupt_payload,
    gate_check,
    make_gate_id,
    parse_resume_decision,
)
from schemas import ModelSpec, RiskProfile, RiskThresholds
from tools.risk.risk_tools import (
    calc_risk,
    generate_risk_profile as build_risk_profile,
    read_blackboard,
    write_pr_comment as write_pr_comment_artifact,
)

try:
    from langgraph.types import Command, interrupt

    _INTERRUPT_AVAILABLE = True
except ImportError:  # pragma: no cover
    Command = None  # type: ignore[assignment,misc]
    interrupt = None  # type: ignore[assignment]
    _INTERRUPT_AVAILABLE = False

HUMAN_REVIEW_NODE = "human_review"


class RiskAgentState(TypedDict, total=False):
    """JSON-serializable state for risk:gate agent."""

    group: str
    flow_name: str
    thread_id: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    artifacts: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    model_spec: dict[str, Any]
    risk_metrics: dict[str, Any]
    risk_profile: dict[str, Any]
    gate_check: dict[str, Any]
    gate_decision: str | None
    gate_id: str | None
    human_gate_payload: dict[str, Any] | None
    pr_comment: dict[str, str] | None
    acceptance: dict[str, Any]
    comment_id: str | None


def run_tool_pipeline(state: RiskAgentState) -> dict[str, Any]:
    """Execute the risk tool sequence (scripted ReAct-compatible pipeline)."""
    input_data = state["input_data"]
    updates: dict[str, Any] = {"artifacts": []}

    blackboard = read_blackboard(input_data)
    spec = ModelSpec(**blackboard["model_spec"])
    model_spec = spec.model_dump(mode="json")
    updates["model_spec"] = model_spec

    scenario = input_data.get("scenario", "normal")
    risk_metrics = calc_risk(model_spec, scenario=scenario)
    updates["risk_metrics"] = risk_metrics

    profile = build_risk_profile(
        model_spec,
        risk_metrics,
        pr_url=input_data.get("pr_url"),
    )
    profile_data = profile.model_dump(mode="json")
    updates["risk_profile"] = profile_data

    artifact_path = Path("artifacts") / "risk" / f"{profile.strategy_id}-profile.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    updates["artifacts"] = [artifact_path.as_posix()]

    thresholds = RiskThresholds()
    check = gate_check(profile, thresholds)
    updates["gate_check"] = check

    if not check["requires_human"]:
        return updates

    gate_id = state.get("gate_id") or make_gate_id(state.get("thread_id", "risk"))
    if _INTERRUPT_AVAILABLE and not state.get("gate_decision"):
        resume_payload = interrupt(
            build_interrupt_payload(
                gate_id=gate_id,
                risk_profile=profile_data,
                reasons=check["reasons"],
            )
        )
        decision = parse_resume_decision(resume_payload)
    else:
        decision = state.get("gate_decision")

    updates.update({
        "gate_id": gate_id,
        "gate_decision": decision,
        "human_gate_payload": build_interrupt_payload(
            gate_id=gate_id,
            risk_profile=profile_data,
            reasons=check["reasons"],
            decision=decision,
        ),
    })
    return updates


def human_review(state: RiskAgentState) -> dict[str, Any]:
    """HumanGate placeholder node (interrupt_before fallback target)."""
    return {}


def write_pr_comment_node(state: RiskAgentState) -> dict[str, Any]:
    """Write PR comment artifact (skip on reject)."""
    if state.get("gate_decision") == "reject":
        return {}

    input_data = state["input_data"]
    profile = RiskProfile(**state["risk_profile"])
    comment_kwargs: dict[str, Any] = {
        "pr_number": str(input_data.get("pr_number", "demo")),
        "head_sha": input_data.get("head_sha", "deadbeef"),
        "pr_url": input_data.get("pr_url"),
        "artifacts_root": input_data.get("artifacts_root", "artifacts/risk/pr-comments"),
        "dedupe_db_path": input_data.get("dedupe_db_path"),
    }
    if "post_to_github" in input_data:
        comment_kwargs["post_to_github"] = input_data["post_to_github"]
    if input_data.get("github_repo"):
        comment_kwargs["github_repo"] = input_data["github_repo"]
    if input_data.get("github_token"):
        comment_kwargs["github_token"] = input_data["github_token"]
    comment = write_pr_comment_artifact(profile, **comment_kwargs)
    return {
        "comment_id": comment["comment_id"],
        "pr_comment": comment,
        "artifacts": [comment["artifact_path"]],
    }


def finalize_output(state: RiskAgentState) -> dict[str, Any]:
    """Run acceptance and assemble output_data."""
    profile_data = state["risk_profile"]
    acceptance = run_acceptance_checks(
        "risk-gate",
        profile_data,
        thresholds=_risk_acceptance_thresholds(),
    )
    acceptance_data = _acceptance_to_dict(acceptance)

    gate_result = state.get("human_gate_payload") or state.get("gate_check") or {}
    human_decision = state.get("gate_decision")
    rejected = human_decision == "reject"
    status = "rejected" if rejected else "completed"
    pr_comment = None if rejected else state.get("pr_comment")

    return {
        "acceptance": acceptance_data,
        "output_data": {
            "status": status,
            "risk_profile": profile_data,
            "gate_result": gate_result,
            "human_decision": human_decision,
            "pr_comment": pr_comment,
            "acceptance": acceptance_data,
        },
    }


def _route_after_pipeline(state: RiskAgentState) -> str:
    gate_check_data = state.get("gate_check") or {}
    if not gate_check_data.get("requires_human"):
        return "write_pr_comment"
    if state.get("gate_decision") == "reject":
        return "finalize_output"
    return HUMAN_REVIEW_NODE


def build_risk_agent(
    checkpoint_db: str | PathLike[str] | None = None,
):
    """Build the LangGraph app for risk:gate (tool-based primary path)."""
    try:
        from langgraph.graph import END

        from runner.langgraph_base import START, create_workflow, get_checkpointer
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph base is not available. Install langgraph and retry."
        ) from exc

    nodes = {
        "run_tool_pipeline": run_tool_pipeline,
        HUMAN_REVIEW_NODE: human_review,
        "write_pr_comment": write_pr_comment_node,
        "finalize_output": finalize_output,
    }
    edges = [
        (START, "run_tool_pipeline"),
        (HUMAN_REVIEW_NODE, "write_pr_comment"),
        ("write_pr_comment", "finalize_output"),
        ("finalize_output", END),
    ]
    workflow = create_workflow(nodes, edges, state_schema=RiskAgentState)
    workflow.add_conditional_edges(
        "run_tool_pipeline",
        _route_after_pipeline,
        {
            "write_pr_comment": "write_pr_comment",
            HUMAN_REVIEW_NODE: HUMAN_REVIEW_NODE,
            "finalize_output": "finalize_output",
        },
    )

    compile_kwargs: dict[str, Any] = {"checkpointer": get_checkpointer(checkpoint_db)}
    if not _INTERRUPT_AVAILABLE:
        compile_kwargs["interrupt_before"] = [HUMAN_REVIEW_NODE]

    return workflow.compile(**compile_kwargs)


def register_risk_gate_flow(
    checkpoint_db: str | PathLike[str] | None = None,
    *,
    overwrite: bool = True,
):
    """Register risk:gate to FLOW_REGISTRY."""
    from runner.compose_executor import register_flow

    app = build_risk_agent(checkpoint_db)
    register_flow("risk", "risk:gate", app, overwrite=overwrite)
    return app


def resume_risk_gate(
    app: Any,
    thread_id: str,
    decision: str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resume a paused risk:gate flow after human review."""
    if not _INTERRUPT_AVAILABLE or Command is None:
        raise RuntimeError("langgraph.types.Command is required to resume risk:gate")

    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if config:
        cfg.update(config)
    return app.invoke(Command(resume={"decision": decision}), config=cfg)


def _risk_acceptance_thresholds() -> dict[str, float]:
    limits = RiskThresholds()
    return {
        "max_drawdown": limits.max_drawdown,
        "position_limit": limits.position_limit_usage,
        "correlation_limit": limits.correlation_limit,
    }


def _acceptance_to_dict(result: AcceptanceResult) -> dict[str, Any]:
    return {
        "verdict": result.verdict,
        "checks": [
            {
                "name": check.name,
                "passed": check.passed,
                "message": check.message,
            }
            for check in result.checks
        ],
    }
