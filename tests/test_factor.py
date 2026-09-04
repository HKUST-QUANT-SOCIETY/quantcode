"""Tests for factor group schemas (FactorSpec / FactorReport)."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from runner.acceptance import run_acceptance
from schemas import (
    BlackboardEntry,
    BlackboardScope,
    BlackboardState,
    ComposeTask,
    FactorReport,
    FactorSpec,
    FactorVerdict,
    GroupName,
    ICMetrics,
    LayeredBacktest,
    TaskOutcome,
    TaskStatus,
    TurnoverMetrics,
    WritePolicy,
)
from schemas.factor import DateRange, DecayMetrics
from tests.fixtures.sample_factor import pb_roe_combo


VALID_SESSION = "S0123456789abcdef"


def _make_factor_spec(**overrides) -> FactorSpec:
    defaults = dict(
        name="pb_roe_combo",
        campaign_id="campaign_2026q2",
        formula="tests.fixtures.sample_factor:pb_roe_combo",
        domain="equity",
        frequency="daily",
        universe="CSI1000",
        operators=["roe_ttm", "pb", "divide"],
        estimated_runtime_seconds=30,
        date_range={"start": "2023-01-01", "end": "2025-12-31"},
        benchmark="HS300",
        forward_return_horizon=5,
    )
    defaults.update(overrides)
    return FactorSpec(**defaults)


def _make_factor_report(**overrides) -> FactorReport:
    defaults = dict(
        factor_name="pb_roe_combo",
        evaluation_period=DateRange(start=date(2023, 1, 1), end=date(2025, 12, 31)),
        universe="CSI1000",
        ic_metrics=ICMetrics(ic_mean=0.05, ic_std=0.08, ir=0.625, t_stat=2.5),
        turnover=TurnoverMetrics(monthly=0.5),
        decay=DecayMetrics(ic_1d=0.06, ic_5d=0.05, ic_20d=0.02),
        layered_backtest=LayeredBacktest(
            top_decile_annual_return=0.12,
            bottom_decile_annual_return=-0.02,
            long_short_annual_return=0.14,
            long_short_sharpe=1.1,
        ),
        verdict=FactorVerdict.PASS,
        eval_run_id="eval-run-001",
        route_recommendation="tier3b_satellite",
        target_tier="Tier3B",
        horizons=[1, 5, 20],
        performance_tags=["high_turnover"],
        action_tags=["needs_smoothing"],
        semantic_label="quality",
        admission_reason="route_recommendation=tier3b_satellite",
    )
    defaults.update(overrides)
    return FactorReport(**defaults)


def test_factor_spec_valid():
    spec = _make_factor_spec()
    assert spec.name == "pb_roe_combo"
    assert spec.campaign_id == "campaign_2026q2"
    assert spec.domain == "equity"
    assert spec.frequency == "daily"
    assert spec.universe == "CSI1000"
    assert spec.forward_return_horizon == 5


def test_factor_spec_required_fields():
    with pytest.raises(ValidationError, match="formula"):
        _make_factor_spec(formula=None)


def test_factor_spec_rejects_bad_date_range():
    with pytest.raises(ValidationError, match="date_range.end"):
        _make_factor_spec(date_range={"start": "2025-12-31", "end": "2023-01-01"})


def test_factor_spec_rejects_duplicate_operators():
    with pytest.raises(ValidationError, match="operators must be unique"):
        _make_factor_spec(operators=["roe_ttm", "pb", "pb"])


def test_factor_report_valid():
    report = _make_factor_report()
    assert report.ic_metrics.ic_mean == 0.05
    assert report.turnover.monthly == 0.5
    assert report.verdict == FactorVerdict.PASS
    assert report.route_recommendation == "tier3b_satellite"
    assert report.target_tier == "Tier3B"


def test_factor_evaluation_as_compose_task():
    spec = _make_factor_spec()
    report = _make_factor_report()

    task = ComposeTask[FactorSpec, FactorReport](
        task_id="T4",
        session_id=VALID_SESSION,
        root_task_id="T4",
        group=GroupName.FACTOR,
        status=TaskStatus.DONE,
        outcome=TaskOutcome.SUCCESS,
        summary="Evaluate PB-ROE factor",
        input=spec,
        output=report,
    )

    assert task.input.name == "pb_roe_combo"
    assert task.output is not None
    assert task.output.ic_metrics.ir == 0.625


def test_factor_result_shared_via_project_blackboard():
    report = _make_factor_report()
    bb = BlackboardState(session_id=VALID_SESSION)
    entry = BlackboardEntry(
        scope=BlackboardScope.PROJECT,
        group=None,
        key="shared.factor_evaluation_results.pb_roe_combo",
        write_policy=WritePolicy.GROUP_APPEND,
        value=report.model_dump(mode="json"),
        written_by_task_id="T4",
        written_by_group=GroupName.FACTOR,
    )

    bb.add_entry(entry)
    retrieved = bb.get_entry(
        BlackboardScope.PROJECT,
        None,
        "shared.factor_evaluation_results.pb_roe_combo",
    )

    assert retrieved is not None
    assert retrieved.value["factor_name"] == "pb_roe_combo"
    assert retrieved.value["verdict"] == "pass"


def test_factor_report_passes_acceptance_runner():
    report = _make_factor_report()
    result = run_acceptance("factor:evaluation", report.model_dump(mode="json"))
    assert result.verdict == "pass", [c.message for c in result.checks if not c.passed]


def test_factor_report_can_map_autoeval_evaluation_block():
    autoeval_evaluation = {
        "Label": "Evaluated",
        "eval_run_id": "eval-run-001",
        "route_recommendation": "tier3b_satellite",
        "target_tier": "Tier3B",
        "horizons": [1, 5, 20],
        "key_metrics": {
            "rank_ic_mean": 0.05,
            "rank_ic_ir": 0.625,
            "turnover": 0.5,
            "long_short_sharpe": 1.1,
            "max_drawdown": 0.12,
        },
        "tags": {
            "performance_tags": ["high_turnover"],
            "action_tags": ["needs_smoothing"],
            "semantic_label": "quality",
        },
        "admission_reason": "route_recommendation=tier3b_satellite",
    }

    report = _make_factor_report(
        ic_metrics=ICMetrics(
            ic_mean=autoeval_evaluation["key_metrics"]["rank_ic_mean"],
            ic_std=0.08,
            ir=autoeval_evaluation["key_metrics"]["rank_ic_ir"],
            t_stat=2.5,
        ),
        turnover=TurnoverMetrics(monthly=autoeval_evaluation["key_metrics"]["turnover"]),
        layered_backtest=LayeredBacktest(
            long_short_sharpe=autoeval_evaluation["key_metrics"]["long_short_sharpe"],
        ),
        eval_run_id=autoeval_evaluation["eval_run_id"],
        route_recommendation=autoeval_evaluation["route_recommendation"],
        target_tier=autoeval_evaluation["target_tier"],
        horizons=autoeval_evaluation["horizons"],
        performance_tags=autoeval_evaluation["tags"]["performance_tags"],
        action_tags=autoeval_evaluation["tags"]["action_tags"],
        semantic_label=autoeval_evaluation["tags"]["semantic_label"],
        admission_reason=autoeval_evaluation["admission_reason"],
    )

    assert report.ic_metrics.ic_mean == 0.05
    assert report.ic_metrics.ir == 0.625
    assert report.turnover.monthly == 0.5
    assert report.route_recommendation == "tier3b_satellite"


def test_factor_json_schema_export():
    spec_schema = FactorSpec.model_json_schema()
    report_schema = FactorReport.model_json_schema()
    assert "properties" in spec_schema
    assert "operators" in spec_schema["properties"]
    assert spec_schema["properties"]["operators"]["uniqueItems"] is True
    assert "ic_metrics" in report_schema["properties"]


def test_sample_factor_fixture_callable():
    panel = {"roe_ttm": 0.12, "pb": 2.0}
    assert pb_roe_combo(panel) == 0.06
