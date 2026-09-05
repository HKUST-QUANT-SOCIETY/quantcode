"""Risk evaluation compatibility entry points.

The v5 product path is ReAct.  This deterministic graph remains CI
infrastructure: it evaluates a RiskProfile, writes a report, and never creates
a HumanGate.  Shared writes still use the independent merge/permission gates.
"""
from __future__ import annotations

import json
import operator
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, TypedDict

from runner.acceptance import AcceptanceResult, risk_thresholds, run_acceptance
from schemas import ModelSpec, RiskProfile, RiskThresholds
from tools.risk.risk_tools import (
    calc_risk,
    generate_risk_profile,
    read_blackboard,
    risk_verdict,
    write_pr_comment,
)
from tools.utils.paths import safe_filename_component


class RiskCIState(TypedDict, total=False):
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
    risk_verdict: dict[str, Any]
    pr_comment: dict[str, str] | None
    acceptance: dict[str, Any]
    comment_id: str | None


def evaluate_risk(state: RiskCIState) -> dict[str, Any]:
    """Run the canonical risk adapter sequence and persist the profile artifact."""
    input_data = state["input_data"]
    blackboard = read_blackboard(input_data)
    model_spec = ModelSpec(**blackboard["model_spec"]).model_dump(mode="json")
    metrics = calc_risk(model_spec, scenario=input_data.get("scenario", "normal"))
    profile = generate_risk_profile(model_spec, metrics, pr_url=input_data.get("pr_url"))
    profile_data = profile.model_dump(mode="json")

    artifact_path = Path("artifacts") / "risk" / f"{safe_filename_component(profile.strategy_id)}-profile.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "model_spec": model_spec,
        "risk_metrics": metrics,
        "risk_profile": profile_data,
        "risk_verdict": risk_verdict(profile, RiskThresholds()),
        "artifacts": [artifact_path.as_posix()],
    }


def write_ci_comment(state: RiskCIState) -> dict[str, Any]:
    """Write a pass/fail CI report; breached risk remains visible in the report."""
    input_data = state["input_data"]
    profile = RiskProfile(**state["risk_profile"])
    kwargs: dict[str, Any] = {
        "pr_number": str(input_data.get("pr_number", "demo")),
        "head_sha": input_data.get("head_sha", "deadbeef"),
        "pr_url": input_data.get("pr_url"),
        "artifacts_root": input_data.get("artifacts_root", "artifacts/risk/pr-comments"),
        "dedupe_db_path": input_data.get("dedupe_db_path"),
    }
    for key in ("post_to_github", "github_repo", "github_token"):
        if key in input_data and input_data[key] is not None:
            kwargs[key] = input_data[key]
    comment = write_pr_comment(profile, **kwargs)
    return {
        "comment_id": comment["comment_id"],
        "pr_comment": comment,
        "artifacts": [comment["artifact_path"]],
    }


def finalize_output(state: RiskCIState) -> dict[str, Any]:
    acceptance = run_acceptance(
        "risk-evaluation", state["risk_profile"], thresholds=_risk_acceptance_thresholds()
    )
    acceptance_data = _acceptance_to_dict(acceptance)
    verdict = state["risk_verdict"]
    return {
        "acceptance": acceptance_data,
        "output_data": {
            "status": "completed_with_warning" if verdict.get("breached") else "completed",
            "risk_profile": state["risk_profile"],
            "risk_verdict": verdict,
            "pr_comment": state.get("pr_comment"),
            "acceptance": acceptance_data,
        },
    }


def build_risk_ci_flow(checkpoint_db: str | PathLike[str] | None = None):
    """Build the deterministic Model→Risk GitHub Actions/CI compatibility flow."""
    from langgraph.graph import END
    from runner.langgraph_base import START, create_workflow, get_checkpointer

    workflow = create_workflow(
        {
            "evaluate_risk": evaluate_risk,
            "write_ci_comment": write_ci_comment,
            "finalize_output": finalize_output,
        },
        [
            (START, "evaluate_risk"),
            ("evaluate_risk", "write_ci_comment"),
            ("write_ci_comment", "finalize_output"),
            ("finalize_output", END),
        ],
        state_schema=RiskCIState,
    )
    return workflow.compile(checkpointer=get_checkpointer(checkpoint_db))


def register_risk_ci_flow(
    checkpoint_db: str | PathLike[str] | None = None, *, overwrite: bool = True
):
    from runner.compose_executor import register_flow

    app = build_risk_ci_flow(checkpoint_db)
    register_flow("risk", "risk:ci", app, overwrite=overwrite)
    return app


def run_risk_agent_react(
    task: str,
    *,
    model=None,
    checkpoint_db: str | PathLike[str] | None = None,
    thread_id: str | None = None,
    max_iterations: int = 10,
) -> dict:
    """Run the v5 risk ReAct path; verdicts never interrupt for approval."""
    from runner.agent_engine import AgentRunner

    if model is None:
        from runner.llm_provider import create_deepseek_llm

        model = create_deepseek_llm()
    if checkpoint_db is None:
        raise ValueError("run_risk_agent_react: checkpoint_db is required")

    return AgentRunner(
        group="risk",
        model=model,
        checkpoint_db=checkpoint_db,
        max_iterations=max_iterations,
    ).run(
        task=task,
        skill_name="risk-ci",
        system_prompt=(
            "Read the Blackboard, calculate risk metrics, build RiskProfile, call "
            "risk_verdict, then write the CI report. A breached verdict is a domain "
            "fail/warning and never a HumanGate."
        ),
        thread_id=thread_id,
    )


def _risk_acceptance_thresholds() -> dict[str, float]:
    limits = risk_thresholds()
    return {
        "max_drawdown": limits["max_drawdown"],
        "position_limit": limits["position_limit"],
        "correlation_limit": limits["correlation_limit"],
    }


def _acceptance_to_dict(result: AcceptanceResult) -> dict[str, Any]:
    return {
        "verdict": result.verdict,
        "checks": [
            {"name": check.name, "passed": check.passed, "message": check.message}
            for check in result.checks
        ],
    }


__all__ = [
    "RiskCIState",
    "evaluate_risk",
    "write_ci_comment",
    "finalize_output",
    "build_risk_ci_flow",
    "register_risk_ci_flow",
    "run_risk_agent_react",
]
