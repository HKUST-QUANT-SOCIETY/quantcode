"""deployment_candidate tool — 生成交给 Admin 的待部署状态，不执行生产部署。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.registry import ToolDef


class DeploymentCandidateArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    verdict: str = Field(default="pass", description="StrategyReport.verdict")
    artifact_path: str | None = Field(
        default=None,
        description="可选：StrategyReport JSON 路径",
    )


def deployment_candidate_execute(args: DeploymentCandidateArgs, ctx: dict) -> dict:
    if args.verdict in ("needs_human", "fail"):
        return {
            "status": "validation_failed",
            "strategy_name": args.strategy_name,
            "deployed": False,
            "message": (
                f"Deploy blocked for {args.strategy_name}: "
                f"verdict={args.verdict}"
            ),
            "artifact_path": args.artifact_path,
        }
    return {
        "status": "pending_admin",
        "strategy_name": args.strategy_name,
        "deployed": False,
        "message": f"{args.strategy_name} is ready for Admin deployment review",
        "artifact_path": args.artifact_path,
    }


deployment_candidate_tool = ToolDef(
    id="deployment_candidate",
    description=(
        "Prepare a strategy deployment request for the Admin management surface. "
        "This tool never deploys to production and returns deployed=false. "
        "Returns validation_failed for a failed verdict. "
        "Input: strategy_name, verdict and optional artifact_path."
    ),
    schema=DeploymentCandidateArgs,
    execute=deployment_candidate_execute,
    permission=None,
)

__all__ = ["deployment_candidate_tool", "DeploymentCandidateArgs", "deployment_candidate_execute"]
