"""Tests for the Day 2 factor:autoeval flow nodes."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from flows.factor_autoeval import (
    build_workflow,
    call_autoeval_api,
    generate_factor_report,
    run_acceptance,
    validate_factor_spec,
)
from schemas import FactorReport, FactorVerdict


def _make_input_data(**overrides):
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


def _run_nodes(input_data):
    state = {
        "group": "factor",
        "flow_name": "factor:autoeval",
        "input_data": input_data,
        "artifacts": [],
        "errors": [],
    }
    state.update(validate_factor_spec(state))
    state.update(call_autoeval_api(state))
    state.update(generate_factor_report(state))
    state.update(run_acceptance(state))
    return state


def test_validate_factor_spec_accepts_pb_roe_input():
    result = validate_factor_spec({"input_data": _make_input_data()})

    assert result["input_spec"]["name"] == "pb_roe_combo"
    assert result["input_spec"]["operators"] == ["roe_ttm", "pb", "divide"]


def test_validate_factor_spec_rejects_duplicate_operators():
    with pytest.raises(ValidationError, match="operators must be unique"):
        validate_factor_spec({"input_data": _make_input_data(operators=["roe_ttm", "pb", "pb"])})


def test_mock_autoeval_result_is_stable_and_acceptance_ready():
    state = {"input_spec": validate_factor_spec({"input_data": _make_input_data()})["input_spec"]}

    result = call_autoeval_api(state)

    assert result["eval_result"]["ic_mean"] == 0.045
    assert result["eval_result"]["ir"] == 0.8
    assert result["eval_result"]["turnover_monthly"] == 0.25
    assert result["eval_result"]["t_stat"] == 2.5


def test_generate_factor_report_writes_valid_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {
        "input_spec": validate_factor_spec({"input_data": _make_input_data()})["input_spec"],
    }
    state.update(call_autoeval_api(state))

    result = generate_factor_report(state)

    report = FactorReport(**result["report"])
    assert report.factor_name == "pb_roe_combo"
    assert report.verdict == FactorVerdict.PASS
    assert result["output_data"] == result["report"]

    artifact_path = tmp_path / result["artifacts"][0]
    assert artifact_path.exists()
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert FactorReport(**artifact_payload).factor_name == "pb_roe_combo"


def test_run_acceptance_passes_for_mock_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _run_nodes(_make_input_data())

    assert state["acceptance"]["verdict"] == "pass"
    assert all(check["passed"] for check in state["acceptance"]["checks"])


def test_factor_autoeval_langgraph_app_invoke(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    from runner.langgraph_base import clear_checkpointer_cache, make_thread_id

    monkeypatch.chdir(tmp_path)
    app = build_workflow(checkpoint_db=tmp_path / "checkpoints.db")
    thread_id = make_thread_id("factor", "factor:autoeval", ts=1, suffix="test")

    try:
        result = app.invoke(
            {
                "group": "factor",
                "flow_name": "factor:autoeval",
                "thread_id": thread_id,
                "input_data": _make_input_data(),
                "output_data": None,
                "artifacts": [],
                "errors": [],
            },
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        clear_checkpointer_cache()

    assert result["acceptance"]["verdict"] == "pass"
    assert result["output_data"]["factor_name"] == "pb_roe_combo"
    assert (tmp_path / result["artifacts"][0]).exists()


def test_factor_autoeval_execute_compose_flow(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")

    from runner.compose_executor import execute_compose_flow, register_flow, unregister_flow
    from runner.langgraph_base import clear_checkpointer_cache, make_thread_id

    monkeypatch.chdir(tmp_path)
    thread_id = make_thread_id("factor", "factor:autoeval", ts=3, suffix="executor")
    register_flow("factor", "factor:autoeval", build_workflow(tmp_path / "checkpoints.db"), overwrite=True)
    try:
        result = execute_compose_flow(
            group="factor",
            flow_name="factor:autoeval",
            input_data=_make_input_data(),
            thread_id=thread_id,
        )
    finally:
        unregister_flow("factor", "factor:autoeval")
        clear_checkpointer_cache()

    assert result["thread_id"] == thread_id
    assert result["errors"] == []
    assert FactorReport(**result["output_data"]).factor_name == "pb_roe_combo"
    assert result["state"]["acceptance"]["verdict"] == "pass"
    assert (tmp_path / result["artifacts"][0]).exists()
