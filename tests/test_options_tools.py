"""Tests for options group tools — Day 3 刘炽。"""
from __future__ import annotations

import importlib

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
            "write_artifact": True,
        },
    )
    assert result["underlying"] == "GC"
    assert len(result["points"]) >= 1
    assert 0 <= result["points"][0]["implied_vol"] <= 5
    assert result["interpolation_method"] == "black_scholes_iv_bisection"
    assert result.get("artifact_path")
    assert result["data_quality"] in {"sample_bs_iv", "sample", "mock"}


def test_build_vol_surface_does_not_use_substring_underlying_match(tmp_path, monkeypatch):
    import tools.options.build_vol_surface as surface

    data = tmp_path / "quotes.csv"
    data.write_text(
        "underlying,strike_price,mid_px,instrument_class,expiration\n"
        "GCZ6,3400,40,call,2026-12-25\n"
        "GOLD,3400,40,call,2026-12-25\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(surface, "PROJECT_ROOT", tmp_path)
    result = surface.build_vol_surface_execute(
        surface.BuildVolSurfaceArgs(
            strategy_name="s",
            underlying="G",
            as_of_date="2026-06-27",
            data_path=str(data),
            write_artifact=False,
        ),
        {},
    )
    assert result["data_quality"] == "mock"


def test_option_artifact_strategy_name_cannot_escape_root(tmp_path, monkeypatch):
    import tools.options.build_vol_surface as surface

    monkeypatch.setattr(surface, "PROJECT_ROOT", tmp_path)
    result = surface.build_vol_surface_execute(
        surface.BuildVolSurfaceArgs(
            strategy_name=r"..\\outside/strategy",
            underlying="GC",
            as_of_date="2026-06-27",
            data_path=str(tmp_path / "missing.csv"),
            write_artifact=True,
        ),
        {},
    )
    artifact = tmp_path / result["artifact_path"]
    assert artifact.is_file()
    assert artifact.resolve().is_relative_to((tmp_path / "artifacts" / "options").resolve())


def test_build_vol_surface_rejects_external_data_path_in_production(tmp_path, monkeypatch):
    import tools.options.build_vol_surface as surface

    monkeypatch.delenv("QUANTCODE_ENV", raising=False)
    with pytest.raises(ValueError, match="inside the approved"):
        surface.build_vol_surface_execute(
            surface.BuildVolSurfaceArgs(
                strategy_name="gc_vol_carry",
                underlying="GC",
                as_of_date="2026-06-27",
                data_path=str(tmp_path / "quotes.csv"),
                write_artifact=False,
            ),
            {},
        )


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


def test_calc_greeks_scales_portfolio_by_contract_quantity():
    from tools.options.calc_greeks import CalcGreeksArgs, calc_greeks_execute

    one = calc_greeks_execute(
        CalcGreeksArgs(
            underlying="GC",
            as_of_date="2026-06-27",
            spot_price=3400.0,
            call_quantity=1,
        ),
        {},
    )
    ten = calc_greeks_execute(
        CalcGreeksArgs(
            underlying="GC",
            as_of_date="2026-06-27",
            spot_price=3400.0,
            call_quantity=10,
        ),
        {},
    )
    for key in ("delta", "gamma", "vega", "theta"):
        assert ten["portfolio_greeks"][key] == pytest.approx(
            10 * one["portfolio_greeks"][key]
        )


def test_calc_greeks_rejects_missing_surface_artifact(tmp_path):
    from tools.options.calc_greeks import CalcGreeksArgs, calc_greeks_execute

    with pytest.raises(ValueError, match="surface artifact"):
        calc_greeks_execute(
            CalcGreeksArgs(
                underlying="GC",
                as_of_date="2026-06-27",
                surface_artifact_path=str(tmp_path / "missing.json"),
            ),
            {},
        )


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
