"""Register risk group tools to the global registry."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from schemas.risk_profile import RiskProfile, RiskThresholds
from tools.common.request_human_review import request_human_review_tool
from tools.registry import ToolDef, register_tool
from tools.risk import risk_tools


class ReadBlackboardArgs(BaseModel):
    input_data: dict[str, Any] = Field(
        description="Flow input; may include project_id, blackboard_db_path, blackboard_key"
    )


class CalcRiskArgs(BaseModel):
    model_spec: dict[str, Any]
    scenario: str = Field(default="normal", description="normal or high_risk stub scenario")


class GenerateRiskProfileArgs(BaseModel):
    model_spec: dict[str, Any]
    risk_metrics: dict[str, Any]
    pr_url: str | None = None


class CheckGateArgs(BaseModel):
    risk_profile: dict[str, Any]
    thresholds: dict[str, Any] | None = None


class WritePrCommentArgs(BaseModel):
    risk_profile: dict[str, Any]
    pr_number: str
    head_sha: str
    pr_url: str | None = None
    artifacts_root: str = "artifacts/risk/pr-comments"
    dedupe_db_path: str | None = None
    post_to_github: bool | None = None


def _read_blackboard_execute(args: ReadBlackboardArgs, ctx: dict) -> dict[str, Any]:
    return risk_tools.read_blackboard(args.input_data)


def _calc_risk_execute(args: CalcRiskArgs, ctx: dict) -> dict[str, Any]:
    return risk_tools.calc_risk(args.model_spec, scenario=args.scenario)


def _generate_risk_profile_execute(args: GenerateRiskProfileArgs, ctx: dict) -> dict[str, Any]:
    profile = risk_tools.generate_risk_profile(
        args.model_spec, args.risk_metrics, pr_url=args.pr_url
    )
    return {"risk_profile": profile.model_dump(mode="json")}


def _check_gate_execute(args: CheckGateArgs, ctx: dict) -> dict[str, Any]:
    profile = RiskProfile(**args.risk_profile)
    thresholds = RiskThresholds(**args.thresholds) if args.thresholds else RiskThresholds()
    return risk_tools.check_gate(profile, thresholds)


def _write_pr_comment_execute(args: WritePrCommentArgs, ctx: dict) -> dict[str, Any]:
    profile = RiskProfile(**args.risk_profile)
    kwargs: dict[str, Any] = {
        "pr_number": args.pr_number,
        "head_sha": args.head_sha,
        "pr_url": args.pr_url,
        "artifacts_root": args.artifacts_root,
    }
    if args.dedupe_db_path is not None:
        kwargs["dedupe_db_path"] = args.dedupe_db_path
    if args.post_to_github is not None:
        kwargs["post_to_github"] = args.post_to_github
    return risk_tools.write_pr_comment(profile, **kwargs)


read_blackboard_tool = ToolDef(
    id="read_blackboard",
    description=(
        "Read ModelSpec from Blackboard PROJECT scope (production) or input_data fallback "
        "(test/demo). Call first to obtain model_spec before calc_risk."
    ),
    schema=ReadBlackboardArgs,
    execute=_read_blackboard_execute,
)

calc_risk_tool = ToolDef(
    id="calc_risk",
    description=(
        "Calculate risk metrics for a model_spec using the Day 3 statistics stub. "
        "Use scenario=normal for baseline or high_risk to trigger HumanGate."
    ),
    schema=CalcRiskArgs,
    execute=_calc_risk_execute,
)

generate_risk_profile_tool = ToolDef(
    id="generate_risk_profile",
    description=(
        "Build a validated RiskProfile from model_spec and calc_risk output. "
        "Call after calc_risk and before check_gate."
    ),
    schema=GenerateRiskProfileArgs,
    execute=_generate_risk_profile_execute,
)

check_gate_tool = ToolDef(
    id="check_gate",
    description=(
        "Evaluate RiskProfile against RiskThresholds. Returns requires_human and reasons. "
        "If requires_human is true, pause for HumanGate approval before write_pr_comment."
    ),
    schema=CheckGateArgs,
    execute=_check_gate_execute,
)

write_pr_comment_tool = ToolDef(
    id="write_pr_comment",
    description=(
        "Write QuantCode Risk Gate Report to local artifact and optionally GitHub PR comment. "
        "Only call after check_gate passes OR HumanGate approves. "
        "Same PR + head_sha + profile is deduped."
    ),
    schema=WritePrCommentArgs,
    execute=_write_pr_comment_execute,
)

register_tool(read_blackboard_tool)
register_tool(calc_risk_tool)
register_tool(generate_risk_profile_tool)
register_tool(check_gate_tool)
register_tool(write_pr_comment_tool)
register_tool(request_human_review_tool)  # Day 4 俞高磊：注册 HumanGate interrupt tool

__all__ = [
    "read_blackboard_tool",
    "calc_risk_tool",
    "generate_risk_profile_tool",
    "check_gate_tool",
    "write_pr_comment_tool",
    "request_human_review_tool",
]
