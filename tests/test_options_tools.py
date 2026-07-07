"""Tests for options group tools — Day 3 刘炽。"""
from __future__ import annotations

import importlib
from datetime import date

import pytest

from tools.registry import registry

import tools.options._register  # noqa: F401

EXPECTED_TOOL_IDS = {
    "build_vol_surface",
    "calc_greeks",
    "run_options_backtest_stub",
}


@pytest.fixture(autouse=True)
def _ensure_options_tools_registered():
    importlib.reload(tools.options._register)
    yield


def test_options_tools_registered():
    assert EXPECTED_TOOL_IDS.issubset(set(registry.list_ids()))


def test_options_allowlist_filters_tools():
    tools = registry.get_tools_for_group("options")
    assert {t.id for t in tools} == EXPECTED_TOOL_IDS


def test_build_vol_surface_from_sample_csv():
    result = registry.call(
        "build_vol_surface",
        {
            "strategy_name": "gc_vol_carry",
            "underlying": "GC",
            "as_of_date": "2026-06-27",
            "data_path": "data/sample_options/gc_options_merged_sample.csv",
        },
    )
    assert result["underlying"] == "GC"
    assert len(result["points"]) >= 1
    assert 0 <= result["points"][0]["implied_vol"] <= 5


def test_calc_greeks_returns_profile():
    result = registry.call(
        "calc_greeks",
        {
            "underlying": "GC",
            "as_of_date": "2026-06-27",
            "spot_price": 3400.0,
            "call_quantity": 10,
        },
    )
    greeks = result["portfolio_greeks"]
    assert all(k in greeks for k in ("delta", "gamma", "vega", "theta"))


def test_run_options_backtest_stub():
    result = registry.call(
        "run_options_backtest_stub",
        {
            "strategy_name": "gc_vol_carry",
            "underlying": "GC",
            "start_date": "2026-01-01",
            "end_date": "2026-06-27",
        },
    )
    assert result["strategy_name"] == "gc_vol_carry"
    assert 0 <= result["max_drawdown"] <= 1


def test_load_options_compose_skill():
    from tools.skills.loader import load_skill

    text = load_skill("options-compose", group="options")
    assert "build_vol_surface" in text
    assert "calc_greeks" in text
