"""Tests for options group schemas."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from schemas import (
    GreeksProfile,
    GreeksSnapshot,
    OptionSide,
    OptionsBacktestReport,
    OptionsPosition,
    OptionsPositionLeg,
    OptionsSpec,
    VolSurfacePoint,
    VolSurfaceResult,
)


def test_options_spec_valid():
    spec = OptionsSpec(
        strategy_name="gc_vol_carry",
        underlying="GC",
        as_of_date=date(2026, 6, 27),
        data_path="data/sample_options/gc_options_merged_sample.csv",
        research_questions=["曲面是否倒挂？"],
    )
    assert spec.underlying == "GC"


def test_vol_surface_result_valid():
    result = VolSurfaceResult(
        underlying="GC",
        as_of_date=date(2026, 6, 27),
        forward_price=3400.0,
        points=[
            VolSurfacePoint(
                expiry=date(2026, 6, 25),
                strike=3400.0,
                side=OptionSide.CALL,
                implied_vol=0.22,
            )
        ],
    )
    assert len(result.points) == 1


def test_greeks_profile_valid():
    leg = GreeksSnapshot(delta=0.45, gamma=0.02, vega=12.0, theta=-0.8)
    profile = GreeksProfile(
        underlying="GC",
        as_of_date=date(2026, 6, 27),
        portfolio_greeks=leg,
        leg_greeks=[leg],
    )
    assert profile.portfolio_greeks.delta == 0.45


def test_options_position_requires_legs():
    with pytest.raises(ValidationError):
        OptionsPosition(
            underlying="GC",
            as_of_date=date(2026, 6, 27),
            spot_price=3400.0,
            legs=[],
        )


def test_options_backtest_report_valid():
    report = OptionsBacktestReport(
        strategy_name="gc_vol_carry",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 27),
        total_pnl=12500.0,
        max_drawdown=0.08,
        trade_count=42,
    )
    assert report.trade_count == 42
