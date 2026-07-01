"""Tests for model group schemas."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas.model import ModelRiskMetadata, ModelSpec, ModelType


def _valid_model_spec(**overrides) -> ModelSpec:
    data = {
        "model_name": "pb_roe_ranker",
        "model_type": ModelType.BOOSTING,
        "owner": "chen-zhenhong",
        "code_path": "tests/fixtures/sample_model/sample_model.py",
        "training_data_start": date(2021, 1, 1),
        "training_data_end": date(2023, 12, 31),
        "as_of_date": date(2024, 3, 15),
        "hyperparameters": {"n_estimators": 100, "learning_rate": 0.05},
        "feature_dependencies": ["pb", "roe_ttm", "market_cap"],
        "operator_dependencies": ["rank", "zscore"],
        "risk_metadata": {
            "universe": "CSI1000",
            "benchmark": "CSI1000",
            "expected_holding_period_days": 20,
            "max_position_pct": 0.05,
            "uses_leverage": False,
        },
        "commit_sha": "abcdef1",
    }
    data.update(overrides)
    return ModelSpec(**data)


def test_model_spec_valid():
    spec = _valid_model_spec()
    assert spec.model_name == "pb_roe_ranker"
    assert spec.risk_metadata.universe == "CSI1000"


def test_model_spec_rejects_training_range_after_as_of_date():
    with pytest.raises(ValidationError, match="training_data_end"):
        _valid_model_spec(
            training_data_end=date(2024, 4, 1),
            as_of_date=date(2024, 3, 15),
        )


def test_model_spec_rejects_reversed_training_range():
    with pytest.raises(ValidationError, match="training_data_start"):
        _valid_model_spec(
            training_data_start=date(2024, 1, 1),
            training_data_end=date(2023, 12, 31),
        )


def test_model_risk_metadata_requires_leverage_limit_when_levered():
    with pytest.raises(ValidationError, match="leverage_limit"):
        ModelRiskMetadata(uses_leverage=True)


def test_sample_model_metadata_fixture_validates():
    metadata_path = Path("tests/fixtures/sample_model/model_spec.json")
    spec = ModelSpec.model_validate(json.loads(metadata_path.read_text(encoding="utf-8")))
    assert spec.model_type == ModelType.BOOSTING
    assert spec.code_path == "tests/fixtures/sample_model/sample_model.py"
