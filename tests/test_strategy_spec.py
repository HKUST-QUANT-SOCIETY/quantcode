"""Tests for strategy group schemas."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from schemas import (
    BacktestSummary,
    SignalCandidate,
    StrategyReport,
    StrategySpec,
    StrategyVerdict,
)


def test_strategy_spec_valid():
    spec = StrategySpec(
        strategy_name="multi_signal_combo",
        as_of_date=date(2026, 6, 30),
        candidates=[
            SignalCandidate(signal_id="pb_roe_combo", source_group="factor", weight_hint=0.6),
            SignalCandidate(signal_id="pb_roe_ranker", source_group="model", weight_hint=0.4),
        ],
    )
    assert len(spec.candidates) == 2


def test_strategy_report_valid():
    report = StrategyReport(
        strategy_name="multi_signal_combo",
        as_of_date=date(2026, 6, 30),
        selected_signals=["pb_roe_combo", "pb_roe_ranker"],
        weights={"pb_roe_combo": 0.6, "pb_roe_ranker": 0.4},
        backtest=BacktestSummary(
            start_date=date(2023, 1, 1),
            end_date=date(2025, 12, 31),
            annual_return=0.15,
            sharpe=1.2,
            max_drawdown=0.12,
        ),
        verdict=StrategyVerdict.PASS,
    )
    assert report.verdict == StrategyVerdict.PASS


def test_strategy_report_rejects_zero_weights():
    with pytest.raises(ValidationError, match="weights"):
        StrategyReport(
            strategy_name="bad",
            as_of_date=date(2026, 6, 30),
            selected_signals=["a"],
            weights={"a": 0.0},
            backtest=BacktestSummary(
                start_date=date(2023, 1, 1),
                end_date=date(2025, 12, 31),
                max_drawdown=0.1,
            ),
        )
