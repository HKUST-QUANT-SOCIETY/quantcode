"""Tests for risk group tools."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemas.risk_profile import RiskProfile, RiskThresholds
from tools.risk.risk_tools import (
    calc_risk,
    check_gate,
    clear_write_pr_comment_dedupe_cache,
    generate_risk_profile,
    read_blackboard,
    write_pr_comment,
)


@pytest.fixture(autouse=True)
def reset_dedupe_cache():
    clear_write_pr_comment_dedupe_cache()
    yield
    clear_write_pr_comment_dedupe_cache()


def _sample_model_spec() -> dict:
    path = Path(__file__).resolve().parent / "fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_read_blackboard_from_input_data_model_spec():
    model_spec = _sample_model_spec()
    result = read_blackboard({"model_spec": model_spec})

    assert result["model_spec"]["model_name"] == "pb_roe_ranker"


def test_read_blackboard_from_nested_blackboard():
    model_spec = _sample_model_spec()
    result = read_blackboard({"blackboard": {"model_spec": model_spec}})

    assert result["model_spec"]["model_name"] == "pb_roe_ranker"


def test_read_blackboard_raises_when_missing():
    with pytest.raises(KeyError, match="model_spec not found"):
        read_blackboard({"pr_number": "42"})


def test_calc_risk_normal_scenario():
    model_spec = _sample_model_spec()
    metrics = calc_risk(model_spec, scenario="normal")
    profile = generate_risk_profile(model_spec, metrics)
    gate = check_gate(profile, RiskThresholds())

    assert metrics["strategy_id"] == "pb_roe_ranker"
    assert metrics["max_drawdown"] == 0.08
    assert gate["requires_human"] is False


def test_calc_risk_high_risk_scenario():
    model_spec = _sample_model_spec()
    metrics = calc_risk(model_spec, scenario="high_risk")
    profile = generate_risk_profile(model_spec, metrics)
    gate = check_gate(profile, RiskThresholds())

    assert metrics["strategy_id"] == "pb_roe_ranker"
    assert metrics["max_drawdown"] == 0.22
    assert gate["requires_human"] is True


def test_calc_risk_rejects_unknown_scenario():
    with pytest.raises(ValueError, match="Unknown scenario"):
        calc_risk(_sample_model_spec(), scenario="unknown")


def test_generate_risk_profile_from_stub_metrics():
    model_spec = _sample_model_spec()
    metrics = calc_risk(model_spec, scenario="normal")
    pr_url = "https://github.com/hkust-quant-society/quantcode/pull/42"

    profile = generate_risk_profile(model_spec, metrics, pr_url=pr_url)

    assert isinstance(profile, RiskProfile)
    assert profile.strategy_id == "pb_roe_ranker"
    assert profile.pr_url == pr_url
    assert profile.max_drawdown == 0.08


def test_check_gate_normal_profile():
    model_spec = _sample_model_spec()
    profile = generate_risk_profile(model_spec, calc_risk(model_spec, "normal"))
    result = check_gate(profile, RiskThresholds())

    assert result["requires_human"] is False
    assert result["reasons"] == []


def test_check_gate_high_risk_profile():
    model_spec = _sample_model_spec()
    profile = generate_risk_profile(model_spec, calc_risk(model_spec, "high_risk"))
    result = check_gate(profile, RiskThresholds())

    assert result["requires_human"] is True
    assert "max_drawdown" in result["reasons"]
    assert "tail_risk_var_99" in result["reasons"]


def test_write_pr_comment_writes_artifact(tmp_path):
    model_spec = _sample_model_spec()
    profile = generate_risk_profile(model_spec, calc_risk(model_spec, "normal"))

    result = write_pr_comment(
        profile,
        pr_number="42",
        head_sha="abcdef1234567890",
        pr_url="https://github.com/hkust-quant-society/quantcode/pull/42",
        artifacts_root=tmp_path,
        dedupe_db_path=tmp_path / "dedupe.sqlite",
    )

    assert result["comment_id"] == "comment-42-abcdef1"
    artifact = tmp_path / "pr-42-abcdef1.json"
    assert artifact.exists()
    assert result["artifact_path"] == artifact.as_posix()

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["risk_profile"]["strategy_id"] == "pb_roe_ranker"
