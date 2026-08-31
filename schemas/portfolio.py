"""Portfolio schemas — 构建组合 / 调仓计划 / 组合 gate 裁决（PonyTail 极简版）。

数值全部确定性（numpy 纯计算），LLM 零参与。与 schemas/risk_profile.py 同风格。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PortfolioMethod = Literal["equal_weight", "risk_parity", "min_variance"]


class TargetPortfolio(BaseModel):
    """目标组合配置（construct_portfolio 输入）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="组合名；portfolio_id 即取此名。")
    method: PortfolioMethod = "equal_weight"
    max_single_weight: float = Field(default=0.10, gt=0, le=1, description="单资产权重上限。")
    max_gross_exposure: float = Field(default=1.0, gt=0, le=1, description="总仓位（Σw）上限。")
    rebalance_min_turnover: float = Field(
        default=0.05, ge=0, le=1, description="调仓最小换手阈值（小于它的 delta 不动）。"
    )


class PortfolioWeights(BaseModel):
    """构建结果权重向量。"""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str = Field(min_length=1)
    weights: dict[str, float]
    method: PortfolioMethod
    as_of: str = Field(default="", description="ISO-8601 PIT 截面；空=未指定。")
    notes: list[str] = Field(default_factory=list, description="构建注记（如奇异协方差回退）。")


class RebalancePlan(BaseModel):
    """从当前权重到目标权重的调仓计划（权重口径，不含份额换算）。"""

    model_config = ConfigDict(extra="forbid")

    trades: list[dict[str, Any]] = Field(
        description="每项 {asset, from_w, to_w, est_cost}；est_cost 为单笔估计成本（比例口径）。"
    )
    turnover: float = Field(ge=0, description="总换手 = Σ|to_w - from_w|（双边合计）。")
    fee_total: float = Field(ge=0, description="双边佣金 + 卖出印花税合计。")


class PortfolioGateVerdict(BaseModel):
    """组合 gate 裁决（requires_human=True 时附 interrupt payload）。"""

    model_config = ConfigDict(extra="forbid")

    thresholds: dict[str, Any] = Field(description="本次裁决实际使用的阈值。")
    breached: list[str] = Field(default_factory=list, description="超限项名（single_weight/turnover/drawdown_proxy）。")
    requires_human: bool
    reasons: list[str] = Field(default_factory=list, description="人类可读的违规说明。")
    interrupt_payload: dict[str, Any] | None = Field(
        default=None, description="非空时可直接交给 LangGraph interrupt / OpenCode human_gate。"
    )


__all__ = [
    "PortfolioMethod",
    "TargetPortfolio",
    "PortfolioWeights",
    "RebalancePlan",
    "PortfolioGateVerdict",
]