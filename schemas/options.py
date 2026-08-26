"""QuantCode business schemas — options group.

Owner: 刘炽

Compose 流契约：
- OptionsSpec  → build_vol_surface → VolSurfaceResult
- OptionsPosition → calc_greeks → GreeksProfile
- OptionsStrategySpec → run_options_backtest → OptionsBacktestReport

字段对齐 data/sample_options/DataStructure.md 与 gc_options_merged_sample.csv。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ._compat import StrEnum


class OptionSide(StrEnum):
    CALL = "call"
    PUT = "put"


class OptionsDataSource(StrEnum):
    """options 组可用的数据路径类型。"""

    MERGED_CSV = "merged_csv"
    MERGED_PARQUET = "merged_parquet"
    SAMPLE_FIXTURE = "sample_fixture"


class OptionsSpec(BaseModel):
    """options Compose 流输入：描述标的、数据路径与策略 idea。"""

    model_config = ConfigDict(extra="forbid")

    strategy_name: str = Field(min_length=1, max_length=128)
    underlying: str = Field(
        min_length=1,
        max_length=16,
        description="标的代码，如 GC",
        examples=["GC"],
    )
    as_of_date: date
    data_path: str = Field(
        min_length=1,
        description="行情数据路径（repo-relative 或绝对路径）",
        examples=["data/sample_options/gc_options_merged_sample.csv"],
    )
    data_source: OptionsDataSource = OptionsDataSource.SAMPLE_FIXTURE
    research_questions: list[str] = Field(
        default_factory=list,
        description="研究员关心的期权问题，如对冲比例、曲面形态",
    )
    target_expiry: date | None = Field(
        default=None,
        description="聚焦的到期日；None 表示全 term structure",
    )


class VolSurfacePoint(BaseModel):
    """波动率曲面上的一个点（strike × expiry）。"""

    model_config = ConfigDict(extra="forbid")

    expiry: date
    strike: float = Field(gt=0)
    side: OptionSide | None = None
    implied_vol: float = Field(ge=0, le=5, description="隐含波动率（小数，如 0.22 = 22%）")
    moneyness: float | None = Field(default=None, description="strike / forward")


class VolSurfaceResult(BaseModel):
    """build_vol_surface 输出。"""

    model_config = ConfigDict(extra="forbid")

    underlying: str
    as_of_date: date
    forward_price: float = Field(gt=0)
    points: list[VolSurfacePoint] = Field(min_length=1)
    interpolation_method: str = Field(default="svi_stub", max_length=64)
    data_quality: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _points_match_underlying(self) -> "VolSurfaceResult":
        if not self.points:
            raise ValueError("points must not be empty")
        return self


class OptionsPositionLeg(BaseModel):
    """组合中的一个期权腿。"""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    side: OptionSide
    quantity: int = Field(description="合约张数，买为正卖为负")
    strike: float = Field(gt=0)
    expiry: date


class OptionsPosition(BaseModel):
    """calc_greeks 输入：当前持仓。"""

    model_config = ConfigDict(extra="forbid")

    underlying: str
    as_of_date: date
    spot_price: float = Field(gt=0)
    legs: list[OptionsPositionLeg] = Field(min_length=1)


class GreeksSnapshot(BaseModel):
    """单腿或聚合 Greeks。"""

    model_config = ConfigDict(extra="forbid")

    delta: float
    gamma: float = Field(ge=0)
    vega: float
    theta: float
    rho: float | None = None


class GreeksProfile(BaseModel):
    """calc_greeks 输出。"""

    model_config = ConfigDict(extra="forbid")

    underlying: str
    as_of_date: date
    portfolio_greeks: GreeksSnapshot
    leg_greeks: list[GreeksSnapshot] = Field(default_factory=list)
    currency: str = Field(default="USD", max_length=8)


class OptionsStrategySpec(BaseModel):
    """run_options_backtest 输入（Day3 可 stub）。"""

    model_config = ConfigDict(extra="forbid")

    strategy_name: str = Field(min_length=1, max_length=128)
    underlying: str
    start_date: date
    end_date: date
    legs: list[OptionsPositionLeg] = Field(default_factory=list)
    rebalance_rule: str = Field(default="hold_to_expiry", max_length=64)


class OptionsBacktestReport(BaseModel):
    """run_options_backtest_stub 输出。"""

    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    period_start: date
    period_end: date
    total_pnl: float
    max_drawdown: float = Field(ge=0, le=1)
    sharpe: float | None = None
    trade_count: int = Field(ge=0)
    notes: str | None = None
