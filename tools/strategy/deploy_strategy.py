"""deploy_strategy tool — 生成交给 Admin 的待部署状态，不执行生产部署。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.registry import ToolDef


class DeployStrategyArgs(BaseModel):
    strategy_name: str = Field(min_length=1)
    verdict: str = Field(default="pass", description="StrategyReport.verdict")
    require_human: bool = Field(
        default=False,
        description="兼容旧调用方的字段；生产部署统一由 Admin 管理面处理",
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
        "status": "pending_admin",
        "strategy_name": args.strategy_name,
        "deployed": False,
        "message": f"{args.strategy_name} is ready for Admin deployment review",
        "artifact_path": args.artifact_path,
    }


deploy_strategy_tool = ToolDef(
    id="deploy_strategy",
    description=(
        "Prepare a strategy deployment request for the Admin management surface. "
        "This tool never deploys to production and returns deployed=false. "
        "Blocks with needs_human when verdict!=pass or require_human=true. "
        "Input: strategy_name, verdict, optional require_human / artifact_path."
    ),
    schema=DeployStrategyArgs,
    execute=deploy_strategy_execute,
    permission=None,
)

__all__ = ["deploy_strategy_tool", "DeployStrategyArgs", "deploy_strategy_execute"]
