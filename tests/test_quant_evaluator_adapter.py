from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import tools.factor.quant_evaluator_adapter as adapter


def _args() -> adapter.QuantEvaluatorArgs:
    return adapter.QuantEvaluatorArgs(
        factor_panel={
            "_contract": "FactorPanel/v1",
            "factor_id": "fixture_factor",
            "factor_version": "1.2.3",
            "data_snapshot_id": "snapshot-fixture",
            "dates": ["2026-01-02", "2026-01-05"],
            "assets": ["600000.SH", "000001.SZ"],
            "values": [[1.0, 2.0], [2.0, 1.0]],
            "source_path": "fixture://factor-panel",
        },
        label_bundle={
            "target_id": "fwd_vwap_1d",
            "values": [[0.01, -0.01], [0.02, -0.02]],
            "horizon": 1,
            "decision_time": ["2026-01-02", "2026-01-05"],
            "label_start_time": ["2026-01-02", "2026-01-05"],
            "label_end_time": ["2026-01-03", "2026-01-06"],
            "source_ref": "fixture://explicit-forward-returns",
        },
        metric_ids=("rank_ic", "coverage"),
    )


def test_missing_package_is_truthfully_unavailable(monkeypatch):
    def missing():
        raise ModuleNotFoundError("fixture")

    monkeypatch.setattr(adapter, "_load_runtime", missing)
    result = adapter.quant_evaluator_execute(_args(), {})
    assert result["result_status"] == "UNAVAILABLE"
    assert result["output_data"] is None
    assert result["artifacts"] == []


def test_real_interface_translation_writes_hashed_artifact(tmp_path, monkeypatch):
    captured = {}

    class ValueObject:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @dataclass(frozen=True)
    class Bundle:
        request_id: str
        factor_ids: tuple[str, ...]
        metric_values: dict
        warnings: tuple[str, ...] = ()

    def evaluate(factors, labels, *, metrics):
        captured.update(factors=factors, labels=labels, metrics=metrics)
        return Bundle("request-fixture", factors.factor_ids, {"rank_ic": 1.0})

    monkeypatch.setattr(
        adapter,
        "_load_runtime",
        lambda: (evaluate, ValueObject, ValueObject, ValueObject),
    )
    result = adapter.quant_evaluator_execute(_args(), {"artifact_root": tmp_path})

    assert result["result_status"] == "SUCCEEDED"
    assert captured["factors"].values.shape == (2, 2, 1)
    assert captured["labels"].values.shape == (2, 2)
    assert captured["labels"].decision_time == (date(2026, 1, 2), date(2026, 1, 5))
    assert captured["metrics"] == ("rank_ic", "coverage")
    artifact = result["artifacts"][0]
    path = Path(artifact["path"])
    assert path.exists()
    assert len(artifact["sha256"]) == 64
    assert "snapshot-fixture" in path.read_text(encoding="utf-8")


def test_label_dates_must_match_factor_panel():
    args = _args()
    args.label_bundle.decision_time[1] = date(2026, 1, 7)
    result = adapter.quant_evaluator_execute(args, {})
    assert result["result_status"] == "FAILED"
    assert "exactly match" in result["errors"][0]
