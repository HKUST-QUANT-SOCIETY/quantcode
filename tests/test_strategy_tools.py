"""Tests for strategy group tools — Day 4 刘炽。"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from schemas.strategy import StrategyReport
from tools.registry import PROJECT_ROOT, registry

import tools.strategy._register  # noqa: F401

EXPECTED = {
    "select_signals",
    "combine_signals",
    "run_strategy_backtest",
    "deploy_strategy",
}


@pytest.fixture(autouse=True)
def _ensure_registered():
    importlib.reload(tools.strategy._register)
    yield


def test_strategy_tools_registered():
    assert EXPECTED.issubset(set(registry.list_ids()))


def test_strategy_allowlist():
    assert {t.id for t in registry.get_tools_for_group("strategy")} == {
        "select_signals",
        "combine_signals",
        "run_strategy_backtest",
    }


def test_select_combine_backtest_pipeline():
    fixture = json.loads(
        (PROJECT_ROOT / "tests/fixtures/strategy_backtest_result.json").read_text(
            encoding="utf-8"
        )
    )
    selected = registry.call(
        "select_signals",
        {
            "candidates": fixture["candidates"],
            "max_positions": 3,
            "min_weight_hint": 0.05,
        },
    )
    assert len(selected["selected"]) == 3

    combined = registry.call(
        "combine_signals",
        {"selected": selected["selected"], "target_gross_exposure": 1.0},
    )
    assert abs(sum(combined["weights"].values()) - 1.0) < 1e-5

    report = registry.call(
        "run_strategy_backtest",
        {
            "strategy_name": fixture["strategy_name"],
            "as_of_date": fixture["as_of_date"],
            "weights": combined["weights"],
        },
    )
    validated = StrategyReport.model_validate(report)
    assert validated.strategy_name == fixture["strategy_name"]
    assert len(validated.selected_signals) >= 1
    assert 0 <= validated.backtest.max_drawdown <= 1


def test_deploy_strategy_needs_human():
    result = registry.call(
        "deploy_strategy",
        {"strategy_name": "x", "verdict": "needs_human"},
    )
    assert result["deployed"] is False
    assert result["status"] == "needs_human"


def test_deploy_strategy_only_creates_admin_request():
    """策略 Agent 只能生成待部署状态，不能宣称已部署。"""
    result = registry.call(
        "deploy_strategy",
        {"strategy_name": "x", "verdict": "pass"},
    )
    assert result["deployed"] is False
    assert result["status"] == "pending_admin"
    assert "Admin" in result["message"]


def test_load_strategy_compose_skill():
    from tools.skills.loader import load_skill

    text = load_skill("strategy-compose", group="strategy")
    assert "select_signals" in text
    assert "StrategyReport" in text
