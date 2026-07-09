"""deploy_strategy tool — 部署占位；超阈值或显式 require_human 时返回 needs_human。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.registry import ToolDef


class DeployStrategyArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    verdict: str = Field(default="pass", description="StrategyReport.verdict")
    require_human: bool = Field(
        default=False,
        description="强制走 HumanGate（Permission ask）",
    )
    artifact_path: str | None = Field(
        default=None,
        description="可选：StrategyReport JSON 路径",
    )


def deploy_strategy_execute(args: DeployStrategyArgs, ctx: dict) -> dict:
    if args.require_human or args.verdict in ("needs_human", "fail"):
        return {
            "status": "needs_human",
            "strategy_name": args.strategy_name,
            "deployed": False,
            "message": (
                f"Deploy blocked for {args.strategy_name}: "
                f"verdict={args.verdict}, require_human={args.require_human}"
            ),
            "artifact_path": args.artifact_path,
        }
    return {
        "status": "deployed_stub",
        "strategy_name": args.strategy_name,
        "deployed": True,
        "message": f"[stub] {args.strategy_name} marked ready for production",
        "artifact_path": args.artifact_path,
    }


deploy_strategy_tool = ToolDef(
    id="deploy_strategy",
    description=(
        "Deploy a strategy to production (stub). "
        "Blocks with needs_human when verdict!=pass or require_human=true. "
        "Input: strategy_name, verdict, optional require_human / artifact_path."
    ),
    schema=DeployStrategyArgs,
    execute=deploy_strategy_execute,
)

__all__ = ["deploy_strategy_tool", "DeployStrategyArgs", "deploy_strategy_execute"]
