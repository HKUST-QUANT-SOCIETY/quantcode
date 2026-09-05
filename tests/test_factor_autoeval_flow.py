"""Factor evaluation adapter v5 tests (filename retained for test discovery history)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from flows.factor_evaluation_adapter import (
    build_workflow,
    call_quant_evaluator,
    validate_factor_spec,
)


def _spec(**overrides):
    data = {
        "name": "pb_roe_combo",
        "campaign_id": "campaign_2026q2",
        "formula": "tests.fixtures.sample_factor:pb_roe_combo",
        "domain": "equity",
        "frequency": "daily",
        "universe": "CSI1000",
        "operators": ["roe_ttm", "pb", "divide"],
        "estimated_runtime_seconds": 30,
        "date_range": {"start": "2023-01-01", "end": "2025-12-31"},
        "benchmark": "HS300",
        "forward_return_horizon": 5,
    }
    data.update(overrides)
    return data


def test_validate_factor_spec():
    assert validate_factor_spec({"input_data": _spec()})["input_spec"]["name"] == "pb_roe_combo"
    with pytest.raises(ValidationError):
        validate_factor_spec({"input_data": _spec(operators=["pb", "pb"])})


def test_unconfigured_quant_evaluator_is_explicitly_unavailable(monkeypatch):
    monkeypatch.delenv("QUANT_EVALUATOR_API_URL", raising=False)
    monkeypatch.delenv("QUANT_EVALUATOR_API_KEY", raising=False)
    state = validate_factor_spec({"input_data": _spec()})
    result = call_quant_evaluator(state)
    assert result["component_result"]["result_status"] == "UNAVAILABLE"
    assert result["component_result"]["output_data"] is None
    assert result["errors"]


def test_flow_returns_truthful_unavailable_result(tmp_path, monkeypatch):
    monkeypatch.delenv("QUANT_EVALUATOR_API_URL", raising=False)
    monkeypatch.delenv("QUANT_EVALUATOR_API_KEY", raising=False)
    app = build_workflow(tmp_path / "checkpoints.db")
    state = app.invoke(
        {"group": "factor", "flow_name": "factor:evaluation", "input_data": _spec(),
         "artifacts": [], "errors": []},
        config={"configurable": {"thread_id": "factor-evaluation-test"}},
    )
    assert state["output_data"]["result_status"] == "UNAVAILABLE"
    assert state["artifacts"] == []
