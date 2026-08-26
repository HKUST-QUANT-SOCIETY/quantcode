"""
QuantCode business schemas — factor group.

Owner: 肖骥超

Business schemas are used as ComposeTask[TIn, TOut] type parameters:
- FactorSpec -> ComposeTask[FactorSpec, FactorReport]
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from ._compat import StrEnum


OperatorName = Annotated[str, StringConstraints(min_length=1)]


class ICMethod(StrEnum):
    """Information coefficient calculation method."""

    PEARSON = "pearson"
    SPEARMAN = "spearman"


class FactorVerdict(StrEnum):
    """factor:autoeval runner verdict."""

    PASS = "pass"
    FAIL = "fail"
    MARGINAL = "marginal"


class DateRange(BaseModel):
    """Inclusive evaluation date range."""

    model_config = ConfigDict(extra="forbid")

    start: date = Field(description="Inclusive evaluation start date")
    end: date = Field(description="Inclusive evaluation end date")

    @model_validator(mode="after")
    def _check_order(self) -> "DateRange":
        if self.end < self.start:
            raise ValueError("date_range.end must be greater than or equal to date_range.start")
        return self


class FactorSpec(BaseModel):
    """
    factor Compose flow input contract.

    Used as ComposeTask[FactorSpec, FactorReport].input for factor:autoeval.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        description="Stable factor name; maps to candidate_id when submitted to candidate_pool",
    )
    campaign_id: str | None = Field(
        default=None,
        min_length=1,
        description="Optional AutoFactorEvaluation campaign directory name",
        examples=["campaign_2026q2"],
    )
    formula: str = Field(
        min_length=1,
        description="Factor expression or Python callable reference used to build manifest.json",
        examples=["roe_ttm / pb", "tests.fixtures.sample_factor:pb_roe_combo"],
    )
    domain: str = Field(
        default="equity",
        min_length=1,
        description="Candidate factor domain for Gateway validation",
    )
    frequency: str = Field(
        default="daily",
        min_length=1,
        description="Candidate factor frequency for Gateway validation",
    )
    universe: str = Field(
        default="CSI1000",
        min_length=1,
        description="Evaluation universe, e.g. CSI300/CSI500/CSI1000",
    )
    operators: list[OperatorName] = Field(
        min_length=1,
        json_schema_extra={"uniqueItems": True},
        description="Data fields and operators needed by the factor",
        examples=[["roe_ttm", "pb", "divide", "winsorize", "zscore"]],
    )
    estimated_runtime_seconds: int = Field(
        gt=0,
        description="Expected runtime budget for one AutoEval pipeline run",
    )
    date_range: DateRange = Field(description="AutoEval backtest/evaluation window")
    benchmark: str = Field(
        default="HS300",
        min_length=1,
        description="Benchmark used by AutoFactorEvaluation",
    )
    forward_return_horizon: Literal[1, 3, 5, 10, 20] = Field(
        default=5,
        description="Forward return horizon in trading days",
    )

    @field_validator("operators")
    @classmethod
    def _operators_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("operators must be unique")
        return normalized


class ICMetrics(BaseModel):
    """IC / IR metrics returned by AutoFactorEvaluation."""

    model_config = ConfigDict(extra="forbid")

    ic_mean: float
    ic_std: float = Field(ge=0)
    ir: float
    t_stat: float
    ic_method: ICMethod = ICMethod.SPEARMAN


class TurnoverMetrics(BaseModel):
    """Portfolio turnover summary."""

    model_config = ConfigDict(extra="forbid")

    monthly: float = Field(ge=0)
    annual: float | None = Field(default=None, ge=0)


class DecayMetrics(BaseModel):
    """IC decay by forward-return horizon."""

    model_config = ConfigDict(extra="forbid")

    ic_1d: float | None = None
    ic_3d: float | None = None
    ic_5d: float | None = None
    ic_10d: float | None = None
    ic_20d: float | None = None


class LayeredBacktest(BaseModel):
    """Layered/quantile backtest summary."""

    model_config = ConfigDict(extra="forbid")

    top_decile_annual_return: float | None = None
    bottom_decile_annual_return: float | None = None
    long_short_annual_return: float | None = None
    long_short_sharpe: float | None = None


class FactorReport(BaseModel):
    """
    factor:autoeval output contract.

    Used as ComposeTask[FactorSpec, FactorReport].output.
    """

    model_config = ConfigDict(extra="forbid")

    factor_name: str = Field(min_length=1)
    factor_version: str | None = None
    evaluation_period: DateRange
    universe: str = Field(min_length=1)
    ic_metrics: ICMetrics
    turnover: TurnoverMetrics
    decay: DecayMetrics = Field(default_factory=DecayMetrics)
    layered_backtest: LayeredBacktest = Field(default_factory=LayeredBacktest)
    verdict: FactorVerdict
    fail_reasons: list[str] = Field(default_factory=list)
    eval_run_id: str | None = None
    route_recommendation: str | None = None
    target_tier: str | None = None
    horizons: list[int] = Field(default_factory=list)
    performance_tags: list[str] = Field(default_factory=list)
    action_tags: list[str] = Field(default_factory=list)
    semantic_label: str | None = None
    admission_reason: str | None = None
