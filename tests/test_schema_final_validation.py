"""Day 5 — 6 组 schema 终验（fixtures → Pydantic validate）。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from schemas import (
    FactorReport,
    FactorSpec,
    GreeksProfile,
    ModelSpec,
    OptionsBacktestReport,
    PITResult,
    ResearchResult,
    RiskProfile,
    StrategyReport,
    VolSurfaceResult,
)
from schemas.fundamental import PITQuery
from schemas.options import OptionsSpec
from schemas.strategy import StrategySpec, SignalCandidate
from tools.registry import PROJECT_ROOT

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


def test_schema_model_spec():
    data = json.loads((FIXTURES / "sample_model" / "model_spec.json").read_text())
    ModelSpec.model_validate(data)


def test_schema_risk_profile_normal():
    metrics = json.loads((FIXTURES / "risk_metrics_normal.json").read_text())
    RiskProfile.model_validate(
        {
            "strategy_id": "test-strat",
            "as_of_date": "2026-06-27",
            "max_drawdown": metrics["max_drawdown"],
            "position_limit": metrics["position_limit"],
            "correlation_with_existing": metrics["correlation_with_existing"],
            "capacity_estimate_usd": 1_000_000,
            "tail_risk_var_99": metrics["tail_risk_var_99"],
        }
    )


def test_schema_factor_report():
    data = json.loads((FIXTURES / "factor_backtest_result.json").read_text())
    FactorReport.model_validate(data)


def test_schema_fundamental_pit_and_research():
    pit_raw = json.loads((FIXTURES / "pit_corpus_sample.json").read_text())
    PITQuery(query="test", as_of_date=date(2025, 1, 1), corpus=["all"])
  # corpus sample used by pit_rag tool; validate a minimal PITResult shape
    PITResult.model_validate(
        {
            "query": "蜜雪冰城",
            "as_of_date": "2025-01-01",
            "documents": [
                {
                    "id": d["id"],
                    "source": d["source"],
                    "title": d.get("title"),
                    "published_at": d["published_at"],
                    "snippet": d["snippet"],
                    "score": d["score"],
                    "url": d.get("url"),
                }
                for d in pit_raw["documents"]
                if d["published_at"] <= "2025-01-01"
            ],
            "total_candidates": len(pit_raw["documents"]),
            "filtered_count": 1,
            "retrieval_time_ms": 1,
        }
    )
    ResearchResult.model_validate(
        {
            "markdown_path": "artifacts/research/demo.md",
            "sections_generated": ["overview", "valuation"],
            "citations_count": 5,
            "render_time_ms": 10,
            "word_count": 100,
        }
    )


def test_schema_options_chain():
    OptionsSpec.model_validate(
        {
            "strategy_name": "gc_vol_carry",
            "underlying": "GC",
            "as_of_date": "2026-06-27",
            "data_path": "data/sample_options/gc_options_merged_sample.csv",
        }
    )
    VolSurfaceResult.model_validate(
        {
            "underlying": "GC",
            "as_of_date": "2026-06-27",
            "forward_price": 3400.0,
            "points": [
                {
                    "expiry": "2026-06-25",
                    "strike": 3400.0,
                    "side": "call",
                    "implied_vol": 0.22,
                }
            ],
        }
    )
    GreeksProfile.model_validate(
        {
            "underlying": "GC",
            "as_of_date": "2026-06-27",
            "portfolio_greeks": {
                "delta": 0.5,
                "gamma": 0.03,
                "vega": 14.0,
                "theta": -0.9,
            },
        }
    )
    OptionsBacktestReport.model_validate(
        {
            "strategy_name": "gc_vol_carry",
            "period_start": "2026-01-01",
            "period_end": "2026-06-27",
            "total_pnl": 1000.0,
            "max_drawdown": 0.08,
            "trade_count": 10,
        }
    )


def test_schema_strategy_chain():
    fixture = json.loads((FIXTURES / "strategy_backtest_result.json").read_text())
    StrategySpec.model_validate(
        {
            "strategy_name": fixture["strategy_name"],
            "as_of_date": fixture["as_of_date"],
            "universe": fixture["universe"],
            "candidates": [SignalCandidate.model_validate(c) for c in fixture["candidates"]],
        }
    )
    StrategyReport.model_validate(
        {
            "strategy_name": fixture["strategy_name"],
            "as_of_date": fixture["as_of_date"],
            "selected_signals": ["pb_roe_ranker", "momentum_20d"],
            "weights": {"pb_roe_ranker": 0.5, "momentum_20d": 0.5},
            "backtest": {
                "start_date": "2025-06-27",
                "end_date": fixture["as_of_date"],
                "annual_return": 0.09,
                "sharpe": 1.1,
                "max_drawdown": 0.1,
                "turnover_monthly": 0.2,
            },
        }
    )
