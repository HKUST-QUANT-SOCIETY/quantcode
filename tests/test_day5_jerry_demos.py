"""Day 5 Jerry track end-to-end demo tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.jerry_demos import run_all_demos, run_fundamental_demo, run_options_demo, run_strategy_demo
from tools.registry import PROJECT_ROOT


@pytest.fixture(autouse=True)
def _clean_artifacts(tmp_path, monkeypatch):
  # demos write under artifacts/ — allow writes in repo for test session
    yield


def test_day5_strategy_demo_produces_valid_artifact():
    result = run_strategy_demo()
    assert result["schema"] == "StrategyReport"
    path = PROJECT_ROOT / result["artifact_path"]
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["strategy_name"] == "multi_signal_csi1000"
    assert len(data["selected_signals"]) >= 1


def test_day5_fundamental_demo_pit_safe():
    result = run_fundamental_demo()
    path = PROJECT_ROOT / result["artifact_path"]
    bundle = json.loads(path.read_text(encoding="utf-8"))
    assert bundle["pit_safety"]["all_published_at_lte_as_of"] is True
    assert bundle["pit_safety"]["filtered_count"] >= 1
    assert bundle["pit_safety"]["backend"] in ("chroma", "fixture_json")
    assert bundle["research"]["markdown_path"]
    assert bundle.get("markdown_filled") is True
    assert bundle.get("human_gate", {}).get("decision") == "approve"
    assert "DOC-LEAK-2026" not in {d["id"] for d in bundle["pit"]["documents"]}
    md = (PROJECT_ROOT / bundle["research"]["markdown_path"]).read_text(encoding="utf-8")
    assert "FCF TTM" in md
    assert "Stub content for" not in md


def test_day5_options_demo_produces_options_risk():
    result = run_options_demo()
    path = PROJECT_ROOT / result["artifact_path"]
    bundle = json.loads(path.read_text(encoding="utf-8"))
    assert bundle["vol_surface"]["points"]
    assert bundle["greeks_profile"]["portfolio_greeks"]["delta"] is not None
    assert bundle["backtest"]["max_drawdown"] <= 1.0
    assert (PROJECT_ROOT / bundle["vol_surface"]["artifact_path"]).exists()


def test_day5_all_demos():
    results = run_all_demos()
    assert set(results.keys()) == {"strategy", "fundamental", "options"}
    for track, data in results.items():
        assert (PROJECT_ROOT / data["artifact_path"]).exists(), track
