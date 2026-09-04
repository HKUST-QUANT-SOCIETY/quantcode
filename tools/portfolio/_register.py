"""portfolio tools — 三件套注册（构造/调仓/评估均为确定性数值工具）。

import 即注册（与 tools/market/_register.py 同风格）：
- construct_portfolio(returns_by_asset | cov, config) → PortfolioWeights
- rebalance_plan(current, target, config/thresholds)  → RebalancePlan
- portfolio_verdict(plan, thresholds, equity_curve) → PortfolioVerdict

三个 tool 数值全确定性、LLM 零参与；作为平台级能力走 _meta 通道
（与 list_algorithms 三件套同路），不进各组 tool_allowlist。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef, register_tool


class ConstructPortfolioArgs(BaseModel):
    """construct_portfolio 入参（LLM 可给摘要：资产收益序列或协方差矩阵）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="组合名（即 portfolio_id）。")
    method: str = Field(
        default="equal_weight",
        description="equal_weight | risk_parity | min_variance。",
    )
    returns_by_asset: dict[str, list[float]] | None = Field(
        default=None, description="资产 → 收益序列（优先）；提供则忽略 cov。"
    )
    cov: dict[str, dict[str, float]] | None = Field(
        default=None, description="资产 → 资产 → 协方差（缺项按对角/0 补齐）。"
    )
    max_single_weight: float = Field(default=0.10, gt=0, le=1)
    max_gross_exposure: float = Field(default=1.0, gt=0, le=1)
    rebalance_min_turnover: float = Field(default=0.05, ge=0, le=1)


class RebalancePlanArgs(BaseModel):
    """rebalance_plan 入参（current/target 权重 dict + 可选成本阈值覆盖）。"""

    model_config = ConfigDict(extra="forbid")

    current: dict[str, float] = Field(description="当前权重（缺失资产按 0）。")
    target: dict[str, float] = Field(description="目标权重（缺失资产按 0）。")
    max_single_weight: float | None = None
    rebalance_min_turnover: float | None = Field(
        default=None, ge=0, le=1, description="小于 min_turnover/n 的 delta 不动。"
    )
    commission: float | None = None
    stamp_tax: float | None = None
    thresholds: dict[str, Any] | None = Field(
        default=None, description="可选覆盖 dict（max_single_weight/...），优先级低于同名字段。"
    )


class PortfolioVerdictArgs(BaseModel):
    """portfolio_verdict 入参（thresholds 键名走摘要）。"""

    model_config = ConfigDict(extra="forbid")

    plan: dict[str, Any] = Field(description="rebalance_plan 输出的 RebalancePlan dict。")
    thresholds: dict[str, float] | None = Field(
        default=None,
        description="max_single_weight / max_turnover / max_drawdown_proxy。",
    )
    weights: dict[str, float] | None = Field(
        default=None, description="组合权重快照（供单权重检查；默认用 plan 的 to_w）。"
    )
    equity_curve: list[float] | None = Field(
        default=None, description="可选净值序列 → 回撤代理检查。"
    )

def _construct_execute(args: ConstructPortfolioArgs, ctx: dict) -> dict:
    from schemas.portfolio import TargetPortfolio

    from tools.portfolio.construct import construct_impl

    cfg = TargetPortfolio(
        name=args.name,
        method=args.method,  # type: ignore[arg-type]
        max_single_weight=args.max_single_weight,
        max_gross_exposure=args.max_gross_exposure,
        rebalance_min_turnover=args.rebalance_min_turnover,
    )
    result = construct_impl(cfg, returns_by_asset=args.returns_by_asset, cov=args.cov)
    return result.model_dump(mode="json")


def _rebalance_execute(args: RebalancePlanArgs, ctx: dict) -> dict:
    from tools.portfolio.rebalance import rebalance_plan_impl

    plan = rebalance_plan_impl(
        args.current,
        args.target,
        max_single_weight=args.max_single_weight,
        rebalance_min_turnover=args.rebalance_min_turnover,
        commission=args.commission,
        stamp_tax=args.stamp_tax,
        thresholds=args.thresholds,
    )
    return plan.model_dump(mode="json")


def _verdict_execute(args: PortfolioVerdictArgs, ctx: dict) -> dict:
    from tools.portfolio.gate import portfolio_verdict_impl

    verdict = portfolio_verdict_impl(
        args.plan,
        thresholds=args.thresholds,
        weights=args.weights,
        equity_curve=args.equity_curve,
    )
    return verdict.model_dump(mode="json")


construct_portfolio_tool = ToolDef(
    id="construct_portfolio",
    description=(
        "Deterministically construct portfolio weights (no LLM math): equal_weight, "
        "risk_parity (iterative w~1/sigma, 20 rounds) or min_variance (solve Sigma^-1 1, "
        "singular-cov fallback = equal_weight with note). Applies max_single_weight "
        "capping with 10 rounds of proportional redistribution and gross exposure cap. "
        "Provide returns_by_asset (list of floats per asset) or cov (matrix dict)."
    ),
    schema=ConstructPortfolioArgs,
    execute=_construct_execute,
)

rebalance_plan_tool = ToolDef(
    id="rebalance_plan",
    description=(
        "Build a deterministic rebalance plan from current to target weights: trades "
        "{asset, from_w, to_w, est_cost, side}, total turnover and fees (commission "
        "0.0003 double-sided + sell stamp tax 0.0005 by default). Assets whose |delta| "
        "< rebalance_min_turnover / n are left untouched."
    ),
    schema=RebalancePlanArgs,
    execute=_rebalance_execute,
)

portfolio_verdict_tool = ToolDef(
    id="portfolio_verdict",
    description=(
        "Evaluate a rebalance plan against portfolio thresholds "
        "(max_single_weight, max_turnover, max_drawdown_proxy from optional equity_curve). "
        "Returns a pass/fail verdict and breached reasons. Never creates a HumanGate."
    ),
    schema=PortfolioVerdictArgs,
    execute=_verdict_execute,
)

# 平台级确定性数值工具：走 _meta 通道（不进各组 allowlist），与 algorithms 三件套同路。
for _t in (construct_portfolio_tool, rebalance_plan_tool, portfolio_verdict_tool):
    _t._meta = True  # type: ignore[attr-defined]
    register_tool(_t)  # 覆盖式幂等注册

__all__ = [
    "construct_portfolio_tool",
    "rebalance_plan_tool",
    "portfolio_verdict_tool",
]
