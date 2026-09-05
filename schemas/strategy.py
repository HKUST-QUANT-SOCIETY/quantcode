"""QuantCode business schemas — strategy group.

Owner: 刘炽（Day3 stub）/ 策略组（后续扩展）

Compose 流契约：
- StrategySpec → select/combine/backtest → StrategyReport
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategyVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_HUMAN = "needs_human"


class SignalCandidate(BaseModel):
    """候选信号（因子 / 模型输出）。"""

    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1, max_length=128)
    source_group: str = Field(
        min_length=1,
        description="来源组：factor / model / options",
    )
    weight_hint: float | None = Field(default=None, ge=0, le=1)


class StrategySpec(BaseModel):
    """strategy Compose 流输入。"""

    model_config = ConfigDict(extra="forbid")

    strategy_name: str = Field(min_length=1, max_length=128)
    universe: str = Field(default="CSI1000", min_length=1)
    as_of_date: date
    candidates: list[SignalCandidate] = Field(min_length=1)
    max_positions: int = Field(default=50, ge=1, le=500)
    target_gross_exposure: float = Field(default=1.0, ge=0, le=2)


class BacktestSummary(BaseModel):
    """组合回测摘要。"""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    annual_return: float | None = None
    sharpe: float | None = None
    max_drawdown: float = Field(ge=0, le=1)
    turnover_monthly: float | None = Field(default=None, ge=0)
    # ROADMAP D3b 扩展（可选，回测引擎 internal_v1 填充，旧 stub 调用方无需关心）
    net_value: list[float] | None = None
    turnover_total: float | None = Field(default=None, ge=0)
    fee_total: float | None = Field(default=None, ge=0)
    skipped_days: list[str] | None = None
    gross_exposure_violations: int | None = Field(default=None, ge=0)


class StrategyReport(BaseModel):
    """strategy Compose 流输出。"""

    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    as_of_date: date
    selected_signals: list[str] = Field(min_length=1)
    weights: dict[str, float] = Field(description="signal_id → 权重，总和应接近 1")
    backtest: BacktestSummary
    verdict: StrategyVerdict = StrategyVerdict.PASS
    fail_reasons: list[str] = Field(default_factory=list)
    # ROADMAP D3b：回测引擎标注（internal_v1）；旧 stub 调用方该字段为 None
    engine: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _weights_sum_reasonable(self) -> "StrategyReport":
        if self.weights:
            total = sum(self.weights.values())
            if total <= 0:
                raise ValueError("weights must sum to a positive value")
        return self
