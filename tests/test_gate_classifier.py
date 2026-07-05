"""Tests for runner.routing.gate_classifier — GateClassifier binary model."""
from __future__ import annotations

import pytest

from runner.routing.gate_classifier import (
    FEATURE_NAMES,
    GateClassifier,
    extract_features,
    load_rlhf_dataset,
)


# ---------------------------------------------------------------------------
# Synthetic training data
# ---------------------------------------------------------------------------

def _low_risk_features() -> dict:
    return {
        "tail_risk_var_99": 0.02,
        "max_drawdown": 0.05,
        "volatility": 0.10,
        "position_limit": 0.30,
        "correlation_with_existing": 0.20,
        "var_99_trend": 0.001,
        "max_drawdown_trend": 0.002,
    }


def _high_risk_features() -> dict:
    return {
        "tail_risk_var_99": 0.08,
        "max_drawdown": 0.22,
        "volatility": 0.35,
        "position_limit": 0.92,
        "correlation_with_existing": 0.70,
        "var_99_trend": 0.02,
        "max_drawdown_trend": 0.05,
    }


def _borderline_features() -> dict:
    return {
        "tail_risk_var_99": 0.048,
        "max_drawdown": 0.14,
        "volatility": 0.20,
        "position_limit": 0.78,
        "correlation_with_existing": 0.40,
        "var_99_trend": 0.01,
        "max_drawdown_trend": 0.01,
    }


def _make_labeled(risk_features, label, count=10):
    """Repeat a sample to bulk up training data."""
    return [{"risk_features": risk_features, "label": label} for _ in range(count)]


# ---------------------------------------------------------------------------
# extract_features
# ---------------------------------------------------------------------------

class TestExtractFeatures:
    def test_returns_correct_length(self):
        feats = extract_features(_low_risk_features())
        assert len(feats) == len(FEATURE_NAMES)

    def test_missing_fields_default_to_zero(self):
        feats = extract_features({})
        assert feats == [0.0] * len(FEATURE_NAMES)

    def test_none_fields_default_to_zero(self):
        feats = extract_features({"tail_risk_var_99": None, "max_drawdown": 0.05})
        assert feats[0] == 0.0  # None → 0
        assert feats[1] == 0.05


# ---------------------------------------------------------------------------
# GateClassifier
# ---------------------------------------------------------------------------

class TestGateClassifierTrain:
    def test_train_returns_metrics(self):
        data = _make_labeled(_low_risk_features(), 0, 10) + _make_labeled(
            _high_risk_features(), 1, 10
        )
        clf = GateClassifier()
        report = clf.train(data)
        assert "accuracy" in report
        assert report["n_samples"] == 20
        assert report["accuracy"] > 0.7  # should easily separate these

    def test_train_empty_raises(self):
        clf = GateClassifier()
        with pytest.raises(ValueError, match="empty"):
            clf.train([])

    def test_predict_before_train_raises(self):
        clf = GateClassifier()
        with pytest.raises(RuntimeError, match="not trained"):
            clf.predict(_low_risk_features())


class TestGateClassifierPredict:
    @pytest.fixture(autouse=True)
    def _train(self):
        self.clf = GateClassifier()
        data = _make_labeled(_low_risk_features(), 0, 15) + _make_labeled(
            _high_risk_features(), 1, 15
        )
        self.clf.train(data)

    def test_low_risk_scores_below_05(self):
        prob, reason = self.clf.predict(_low_risk_features())
        assert prob < 0.5, f"low risk should score below 0.5, got {prob}"
        assert isinstance(reason, str)

    def test_high_risk_scores_above_05(self):
        prob, reason = self.clf.predict(_high_risk_features())
        assert prob > 0.5, f"high risk should score above 0.5, got {prob}"
        assert isinstance(reason, str)

    def test_borderline_returns_probability(self):
        prob, _ = self.clf.predict(_borderline_features())
        assert 0.0 <= prob <= 1.0
        # Borderline may go either way — the point is it doesn't crash

    def test_reason_includes_feature_info(self):
        _, reason = self.clf.predict(_high_risk_features())
        assert "GateClassifier" in reason


class TestGateClassifierOverfit:
    """Extreme separation — classifier should achieve 100% accuracy."""

    def test_perfect_separation(self):
        extreme_low = {"tail_risk_var_99": 0.001, "max_drawdown": 0.001,
                       "volatility": 0.01, "position_limit": 0.01,
                       "correlation_with_existing": 0.01,
                       "var_99_trend": 0.0, "max_drawdown_trend": 0.0}
        extreme_high = {"tail_risk_var_99": 0.5, "max_drawdown": 0.8,
                        "volatility": 0.9, "position_limit": 1.0,
                        "correlation_with_existing": 0.9,
                        "var_99_trend": 0.3, "max_drawdown_trend": 0.5}
        data = _make_labeled(extreme_low, 0, 10) + _make_labeled(extreme_high, 1, 10)
        clf = GateClassifier()
        report = clf.train(data, epochs=500)
        assert report["accuracy"] == 1.0

        assert clf.predict(extreme_low)[0] < 0.5
        assert clf.predict(extreme_high)[0] > 0.5


# ---------------------------------------------------------------------------
# RLHF data extraction pattern (integration test)
# ---------------------------------------------------------------------------

class TestRLHFIntegration:
    """Simulate the full pipeline: RLHF records → train → predict."""

    def test_extract_labels_from_rlhf_records(self):
        """Labels can be derived from RLHF feedback fields."""
        rlhf_records = [
            {"risk_features": _high_risk_features(),
             "reward_key": "gate_correct", "label": 1},
            {"risk_features": _low_risk_features(),
             "reward_key": "continue_correct", "label": 0},
            {"risk_features": _low_risk_features(),
             "reward_key": "gate_false_positive", "label": 0},
            {"risk_features": _high_risk_features(),
             "reward_key": "gate_miss", "label": 1},
        ]
        # Train on these
        clf = GateClassifier()
        report = clf.train(rlhf_records)
        assert report["n_samples"] == 4

        # Predict should be directionally correct
        assert clf.predict(_high_risk_features())[0] > clf.predict(_low_risk_features())[0]


# ---------------------------------------------------------------------------
# load_rlhf_dataset
# ---------------------------------------------------------------------------

class TestLoadRlhfDataset:
    """End-to-end: write RLHF JSONL → load → train."""

    def test_loads_labeled_data(self, tmp_path):
        import json
        lines = [
            {"reward_key": "gate_correct", "risk_features": _high_risk_features(),
             "metadata": {"risk_features": _high_risk_features()}},
            {"reward_key": "continue_correct", "risk_features": _low_risk_features(),
             "metadata": {"risk_features": _low_risk_features()}},
            {"reward_key": "gate_false_positive", "risk_features": _low_risk_features(),
             "metadata": {"risk_features": _low_risk_features()}},
            {"reward_key": "gate_miss", "risk_features": _high_risk_features(),
             "metadata": {"risk_features": _high_risk_features()}},
        ]
        path = tmp_path / "rlhf_data.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for rec in lines:
                f.write(json.dumps(rec) + "\n")

        dataset = load_rlhf_dataset(str(path))
        assert len(dataset) == 4
        assert dataset[0]["label"] == 1
        assert dataset[1]["label"] == 0

    def test_skips_non_gate_events(self, tmp_path):
        import json
        lines = [
            {"reward_key": "tool_success", "risk_features": _low_risk_features(),
             "metadata": {"risk_features": _low_risk_features()}},
            {"reward_key": "unknown_event", "risk_features": _high_risk_features(),
             "metadata": {"risk_features": _high_risk_features()}},
        ]
        path = tmp_path / "rlhf_data.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for rec in lines:
                f.write(json.dumps(rec) + "\n")
        dataset = load_rlhf_dataset(str(path))
        assert dataset[0]["label"] == 0  # tool_success → 0
        assert len(dataset) == 1           # unknown_event skipped

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        dataset = load_rlhf_dataset(str(path))
        assert dataset == []

    def test_can_train_from_loaded_data(self, tmp_path):
        import json
        samples = (
            [{"reward_key": "continue_correct", "risk_features": _low_risk_features(),
              "metadata": {"risk_features": _low_risk_features()}}] * 15
            + [{"reward_key": "gate_correct", "risk_features": _high_risk_features(),
                "metadata": {"risk_features": _high_risk_features()}}] * 15
        )
        path = tmp_path / "rlhf_data.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for rec in samples:
                f.write(json.dumps(rec) + "\n")

        dataset = load_rlhf_dataset(str(path))
        assert len(dataset) == 30

        clf = GateClassifier()
        report = clf.train(dataset)
        assert report["accuracy"] > 0.8

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_rlhf_dataset("/nonexistent/path/rlhf.jsonl")
