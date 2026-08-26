"""QuantCode RiskProfile schema — risk:gate 输出契约。

Owner: 杨欣琳（实现）/ 刘炽（schema + fixtures）

对齐：
- schemas/risk-profile.schema.json（main 遗留 JSON）
- tools/risk/statistics_stub.py（normal / high_risk 场景）
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from ._compat import StrEnum


class RiskGateVerdict(StrEnum):
    """risk:gate 评估结论。"""

    PASS = "pass"
    NEEDS_HUMAN = "needs_human"
    REJECTED = "rejected"


class RiskThresholds(BaseModel):
    """HumanGate 默认风控阈值（与 statistics_stub 注释一致）。"""

    model_config = ConfigDict(extra="forbid")

    max_drawdown: float = Field(default=0.15, ge=0, le=1)
    position_limit_usage: float = Field(default=0.8, ge=0, le=1)
    tail_risk_var_99: float = Field(default=0.05, ge=0)
    correlation_limit: float = Field(default=0.6, ge=0, le=1)


class RiskProfile(BaseModel):
    """策略经 risk:gate 分析后的风控画像。

    ComposeTask[ModelSpec, RiskProfile] 的输出契约。
    """

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1, max_length=128)
    as_of_date: date
    max_drawdown: float = Field(ge=0, le=1)
    position_limit: float = Field(ge=0, le=1)
    correlation_with_existing: float = Field(ge=-1, le=1)
    capacity_estimate_usd: float = Field(ge=0)
    tail_risk_var_99: float | None = None
    pr_url: str | None = Field(default=None, max_length=512)
    analyst_notes: str | None = Field(default=None, max_length=4096)

    def evaluate_verdict(self, thresholds: RiskThresholds | None = None) -> RiskGateVerdict:
        """根据阈值判断 gate 结论。"""
        if self.breached_thresholds(thresholds):
            return RiskGateVerdict.NEEDS_HUMAN
        return RiskGateVerdict.PASS

    def breached_thresholds(self, thresholds: RiskThresholds | None = None) -> list[str]:
        """返回超出阈值的指标名列表。"""
        limits = thresholds or RiskThresholds()
        breached: list[str] = []
        if self.max_drawdown > limits.max_drawdown:
            breached.append("max_drawdown")
        if self.position_limit > limits.position_limit_usage:
            breached.append("position_limit")
        if (
            self.tail_risk_var_99 is not None
            and self.tail_risk_var_99 > limits.tail_risk_var_99
        ):
            breached.append("tail_risk_var_99")
        if abs(self.correlation_with_existing) > limits.correlation_limit:
            breached.append("correlation_with_existing")
        return breached
