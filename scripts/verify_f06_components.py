"""Account-independent component smoke for F-06.

This proves package/API execution only. The generated factor values and labels
are explicitly synthetic, so the result is not production evidence and cannot
be used for factor admission.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.factor.quant_evaluator_adapter import (  # noqa: E402
    QuantEvaluatorArgs,
    quant_evaluator_execute,
)


def _installed_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def _data_access_smoke() -> dict:
    from data_access.service.app import create_app

    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    return {
        "health_status": health.status_code,
        "health_body": health.json(),
        "ready_status": ready.status_code,
        "ready_body": ready.json(),
    }


def _quant_evaluator_smoke(artifact_root: Path) -> dict:
    start = date(2026, 1, 2)
    dates = [start + timedelta(days=index) for index in range(30)]
    assets = [f"{600000 + index:06d}.SH" for index in range(60)]
    factor_values = [
        [float(asset_index + time_index % 3) for asset_index in range(len(assets))]
        for time_index in range(len(dates))
    ]
    label_values = [
        [
            float(asset_index) / 10_000 + float(time_index % 5) / 100_000
            for asset_index in range(len(assets))
        ]
        for time_index in range(len(dates))
    ]
    args = QuantEvaluatorArgs(
        factor_panel={
            "_contract": "FactorPanel/v1",
            "factor_id": "synthetic_f06_smoke",
            "factor_version": "fixture-v1",
            "data_snapshot_id": "synthetic-not-production",
            "dates": dates,
            "assets": assets,
            "values": factor_values,
            "source_path": "synthetic://scripts/verify_f06_components.py",
        },
        label_bundle={
            "target_id": "synthetic_fwd_vwap_1d",
            "values": label_values,
            "horizon": 1,
            "decision_time": dates,
            "label_start_time": dates,
            "label_end_time": [item + timedelta(days=1) for item in dates],
            "source_ref": "synthetic://explicit-label-fixture",
            "price_convention": "vwap_to_vwap",
            "metadata": {"production_evidence": False},
        },
        metric_ids=("rank_ic", "coverage"),
    )
    return quant_evaluator_execute(args, {"artifact_root": artifact_root})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts/factor"))
    options = parser.parse_args()
    payload = {
        "evidence_class": "synthetic-component-smoke",
        "production_evidence": False,
        "versions": {
            "data-access": _installed_version("data-access"),
            "factor-engine": _installed_version("factor-engine"),
            "quant_evaluator": _installed_version("quant_evaluator"),
        },
    }
    if payload["versions"]["data-access"]:
        payload["data_access"] = _data_access_smoke()
    if payload["versions"]["quant_evaluator"]:
        payload["quant_evaluator"] = _quant_evaluator_smoke(options.artifact_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(
        payload["versions"][name] for name in ("data-access", "quant_evaluator")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
