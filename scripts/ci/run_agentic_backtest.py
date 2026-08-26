#!/usr/bin/env python3
"""Execute one validated RiskGatePlan through a trusted adapter handler."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from schemas.risk_gate_artifact import (
    BacktestEvidence,
    BacktestRiskMetrics,
    DataObjectEvidence,
    EvidenceStatus,
    RiskApplicability,
    RiskGatePlan,
)


SUPPORTED_ADAPTER = "single-asset-backtrader-v1"
SUPPORTED_DATASET = "cta-benchmark-rb-1m"
EXPECTED_SNAPSHOT_ID = "quant-risk-rb-1m-d31e17-v1"
EXPECTED_DATASET_ID = "cta-benchmark-rb-1m-500k"
MAX_OUTPUT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class AdapterHandler:
    """Trusted dispatch metadata for one executable adapter contract."""

    adapter_id: str
    entrypoint: str
    source_tree: str
    logical_dataset: str
    snapshot_id: str
    snapshot_dataset_id: str
    frequency: str
    symbols: tuple[str, ...]
    required_fields: frozenset[str]
    strategy_name: str
    strategy_version: str
    allowed_parameters: frozenset[str]


ADAPTER_HANDLERS: dict[str, AdapterHandler] = {
    SUPPORTED_ADAPTER: AdapterHandler(
        adapter_id=SUPPORTED_ADAPTER,
        entrypoint="single_asset_backtest.runner:run_single_asset_backtest",
        source_tree="backtest_layer/single_asset_backtest",
        logical_dataset=SUPPORTED_DATASET,
        snapshot_id=EXPECTED_SNAPSHOT_ID,
        snapshot_dataset_id=EXPECTED_DATASET_ID,
        frequency="1min",
        symbols=("rb",),
        required_fields=frozenset({"timestamp", "open", "high", "low", "close", "volume"}),
        strategy_name="dual_ma",
        strategy_version="1.0",
        allowed_parameters=frozenset({"short_window", "long_window", "position_size"}),
    )
}

REQUIRED_RISK_METRICS = frozenset(
    {
        "sharpe",
        "volatility",
        "max_drawdown",
        "tail_risk_var_99",
        "turnover",
        "trading_cost",
        "position_limit",
        "correlation_with_existing",
        "capacity_estimate_usd",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mount_options(path: Path) -> set[str]:
    """Return options for the longest mount point containing ``path``."""

    target = path.resolve(strict=True)
    best: tuple[int, set[str]] | None = None
    for raw in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        left = raw.split(" - ", 1)[0].split()
        if len(left) < 6:
            continue
        mount_point = Path(
            left[4]
            .replace(r"\040", " ")
            .replace(r"\011", "\t")
            .replace(r"\134", "\\")
        )
        try:
            target.relative_to(mount_point)
        except ValueError:
            continue
        candidate = (len(mount_point.as_posix()), set(left[5].split(",")))
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        raise ValueError(f"cannot resolve mount options for {target}")
    return best[1]


def verify_sandbox(
    *, snapshot_root: Path, engine_root: Path, runtime_root: Path
) -> tuple[dict[str, bool], dict[str, str]]:
    """Prove the executor is offline and its trusted inputs are read-only.

    ``/proc`` remains the host procfs in the workflow's nested namespaces, so
    PID 1 provides a stable host-network reference while ``self`` identifies
    the isolated executor process.
    """

    current_net = os.readlink("/proc/self/ns/net")
    host_net = os.readlink("/proc/1/ns/net")
    if current_net == host_net:
        raise ValueError("executor is not running in a distinct network namespace")
    readonly = {
        "snapshot": "ro" in _mount_options(snapshot_root),
        "engine": "ro" in _mount_options(engine_root),
        "runtime": "ro" in _mount_options(runtime_root),
    }
    if not all(readonly.values()):
        failed = sorted(name for name, passed in readonly.items() if not passed)
        raise ValueError(f"executor input is not mounted read-only: {failed}")
    return (
        {
            "network_disabled": True,
            "raw_data_read_only": readonly["snapshot"],
            "engine_read_only": readonly["engine"],
            "runtime_read_only": readonly["runtime"],
            "pr_strategy_source_bound": False,
        },
        {
            "current_network_namespace": current_net,
            "host_network_namespace": host_net,
        },
    )


def json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def source_tree_sha(root: Path, relative_dir: str) -> str:
    source_root = root / relative_dir
    files = sorted(source_root.rglob("*.py"))
    if not files:
        raise FileNotFoundError(f"no adapter source files under {source_root}")
    if any(path.is_symlink() for path in files):
        raise ValueError("adapter source tree must not contain symlinks")
    lines = [f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in files]
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def adapter_handler(adapter_id: str) -> AdapterHandler:
    handler = ADAPTER_HANDLERS.get(adapter_id)
    if handler is None:
        raise ValueError(f"executor has no trusted handler for adapter {adapter_id!r}")
    return handler


def load_plan(path: Path) -> RiskGatePlan:
    plan = RiskGatePlan.model_validate_json(path.read_text(encoding="utf-8"))
    if plan.applicability != RiskApplicability.EVALUABLE:
        raise ValueError(f"executor requires evaluable plan, got {plan.applicability}")
    if plan.adapter is None:
        raise ValueError("executor requires a catalog-bound adapter")
    handler = adapter_handler(plan.adapter.adapter_id)
    if plan.adapter.entrypoint != handler.entrypoint:
        raise ValueError("plan adapter entrypoint does not match the trusted handler")
    if (
        len(plan.data_requests) != 1
        or plan.data_requests[0].logical_dataset != handler.logical_dataset
    ):
        raise ValueError("executor requires exactly one handler-approved snapshot request")
    request = plan.data_requests[0]
    if tuple(request.symbols) != handler.symbols:
        raise ValueError("snapshot symbols do not match the trusted adapter handler")
    if request.require_immutable_snapshot is not True:
        raise ValueError("executor requires an immutable data snapshot")
    if set(request.fields) != handler.required_fields:
        raise ValueError("data request fields do not exactly match the trusted adapter contract")
    if (
        plan.window is None
        or request.start_date != plan.window.oos_start
        or request.end_date != plan.window.oos_end
    ):
        raise ValueError("data request must exactly match the declared OOS window")
    policy = plan.execution_policy
    costs = (
        policy.commission_bps if policy is not None else math.nan,
        policy.slippage_bps if policy is not None else math.nan,
    )
    if (
        policy is None
        or policy.lag_bars != 1
        or policy.fill_time.lower() != "next bar open"
        or not all(math.isfinite(value) and value > 0 for value in costs)
        or policy.stamp_duty_bps != 0
        or policy.enforce_suspension
        or policy.enforce_price_limits
        or policy.enforce_t_plus_one
    ):
        raise ValueError(
            "v1 executor requires one-bar next-open fill, finite non-zero costs, and only "
            "controls implemented by the CTA handler"
        )
    return plan


def load_catalog(path: Path) -> dict[str, Any]:
    catalog = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
        raise ValueError("trusted risk catalog must be a schema_version=1 mapping")
    return catalog


def load_catalog_adapter(path: Path, adapter_id: str) -> dict[str, Any]:
    catalog = load_catalog(path)
    adapter = (catalog.get("adapters") or {}).get(adapter_id)
    if not isinstance(adapter, dict):
        raise ValueError("adapter is absent from trusted catalog")
    return adapter


def validate_catalog_bindings(
    *,
    plan: RiskGatePlan,
    catalog: dict[str, Any],
    handler: AdapterHandler,
    actual_tree: str,
) -> None:
    if plan.adapter is None:
        raise ValueError("executor requires a catalog-bound adapter")
    catalog_adapter = (catalog.get("adapters") or {}).get(handler.adapter_id)
    if not isinstance(catalog_adapter, dict):
        raise ValueError("adapter is absent from trusted catalog")
    identity = {
        "entrypoint": plan.adapter.entrypoint,
        "code_blob_sha256": plan.adapter.code_blob_sha256,
        "engine_id": plan.adapter.engine_id,
        "engine_digest": plan.adapter.engine_digest,
    }
    for field, expected in identity.items():
        if catalog_adapter.get(field) != expected:
            raise ValueError(f"plan/catalog adapter identity mismatch: {field}")
    if identity["entrypoint"] != handler.entrypoint:
        raise ValueError("catalog adapter entrypoint has no matching trusted handler")
    if actual_tree != identity["code_blob_sha256"] or actual_tree != identity["engine_digest"]:
        raise ValueError("backtest adapter requires exact code-blob and engine-tree hashes")

    catalog_dataset = (catalog.get("datasets") or {}).get(handler.logical_dataset)
    if not isinstance(catalog_dataset, dict) or catalog_dataset.get("catalog_only") is not False:
        raise ValueError("data request is not executable in the trusted dataset catalog")
    catalog_fields = set(catalog_dataset.get("fields") or [])
    request_fields = set(plan.data_requests[0].fields)
    if request_fields != handler.required_fields or not request_fields.issubset(catalog_fields):
        raise ValueError("data request contains fields outside the approved dataset contract")
    if catalog_dataset.get("frequency") != handler.frequency:
        raise ValueError("catalog dataset frequency does not match the trusted handler")
    if catalog_dataset.get("immutable_identity") != "content_sha256":
        raise ValueError("catalog dataset lacks the required immutable content identity")

    policy = (catalog.get("risk_policies") or {}).get(plan.risk_policy_id)
    if not isinstance(policy, dict):
        raise ValueError("plan risk policy is absent from the trusted catalog")
    if not REQUIRED_RISK_METRICS.issubset(set(policy.get("required_metrics") or [])):
        raise ValueError("trusted risk policy omits required evidence metrics")


def _normalized_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp


def load_snapshot(root: Path, plan: RiskGatePlan) -> tuple[pd.DataFrame, dict[str, Any], Path]:
    if plan.adapter is None:
        raise ValueError("executor requires a catalog-bound adapter")
    handler = adapter_handler(plan.adapter.adapter_id)
    manifest_path = root / "snapshot-manifest.json"
    data_path = root / "ohlcv.parquet"
    if (
        not manifest_path.is_file()
        or not data_path.is_file()
        or manifest_path.is_symlink()
        or data_path.is_symlink()
    ):
        raise ValueError("snapshot manifest/data must be regular non-symlink files")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("snapshot manifest must be a JSON object")
    if manifest.get("snapshot_id") != handler.snapshot_id or manifest.get("immutable") is not True:
        raise ValueError("unexpected or mutable data snapshot")
    if manifest.get("dataset_id") != handler.snapshot_dataset_id:
        raise ValueError("snapshot dataset identity does not match the trusted handler")
    if manifest.get("logical_dataset", handler.logical_dataset) != handler.logical_dataset:
        raise ValueError("snapshot logical dataset does not match the plan")
    if (
        manifest.get("symbol") not in handler.symbols
        or manifest.get("symbol") not in plan.data_requests[0].symbols
    ):
        raise ValueError("snapshot symbol does not match the plan")
    if manifest.get("frequency") != handler.frequency:
        raise ValueError("snapshot frequency does not match the adapter")
    if sha256_file(data_path) != manifest.get("normalized_content_sha256"):
        raise ValueError("snapshot content hash mismatch")

    frame = pd.read_parquet(data_path)
    required = handler.required_fields
    if not required.issubset(frame.columns):
        raise ValueError(f"snapshot missing columns: {sorted(required - set(frame.columns))}")
    manifest_columns = manifest.get("columns")
    if not isinstance(manifest_columns, list) or set(manifest_columns) != set(frame.columns):
        raise ValueError("snapshot manifest columns do not match materialized data")
    rows = manifest.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows != len(frame):
        raise ValueError("snapshot row count does not match materialized data")
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], utc=True, errors="coerce"
    ).dt.tz_convert(None)
    if (
        frame.empty
        or frame["timestamp"].isna().any()
        or frame["timestamp"].duplicated().any()
        or not frame["timestamp"].is_monotonic_increasing
    ):
        raise ValueError("snapshot is empty, invalid, duplicated, or unsorted")
    manifest_start = _normalized_timestamp(manifest.get("start"))
    manifest_end = _normalized_timestamp(manifest.get("end"))
    if manifest_start != frame["timestamp"].iloc[0] or manifest_end != frame["timestamp"].iloc[-1]:
        raise ValueError("snapshot manifest time range does not match materialized data")

    request = plan.data_requests[0]
    start = pd.Timestamp(request.start_date)
    end = pd.Timestamp(request.end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    if manifest_start.date() > request.start_date or manifest_end.date() < request.end_date:
        raise ValueError("immutable snapshot does not cover the complete requested OOS window")
    frame = frame.loc[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)].copy()
    if (
        frame.empty
        or frame["timestamp"].duplicated().any()
        or not frame["timestamp"].is_monotonic_increasing
    ):
        raise ValueError("snapshot OOS slice is empty, duplicated, or unsorted")
    if (
        frame["timestamp"].iloc[0].date() != request.start_date
        or frame["timestamp"].iloc[-1].date() != request.end_date
    ):
        raise ValueError("snapshot OOS slice does not cover both requested boundary dates")
    return frame, manifest, manifest_path


def run_once(
    *,
    frame: pd.DataFrame,
    plan: RiskGatePlan,
    filtered_path: Path,
) -> tuple[dict[str, Any], str]:
    from single_asset_backtest.config import BacktestConfig
    from single_asset_backtest.runner import run_single_asset_backtest

    if plan.adapter is None:
        raise ValueError("executor requires a catalog-bound adapter")
    handler = adapter_handler(plan.adapter.adapter_id)
    params = dict(plan.adapter_parameters)
    strategy_name = params.pop("strategy_name", None)
    strategy_version = params.pop("strategy_version", handler.strategy_version)
    if not isinstance(strategy_name, str) or not isinstance(strategy_version, str):
        raise ValueError("adapter strategy name and version must be strings")
    if strategy_name != handler.strategy_name:
        raise ValueError(
            f"trusted adapter {handler.adapter_id} allows only strategy {handler.strategy_name}"
        )
    if strategy_version != handler.strategy_version:
        raise ValueError("v1 adapter rejects an unknown strategy version")
    if set(params) - handler.allowed_parameters:
        raise ValueError("adapter parameters contain unapproved keys")
    if not handler.allowed_parameters.issubset(params):
        raise ValueError(f"{handler.strategy_name} adapter parameters are incomplete")
    short_window = params["short_window"]
    long_window = params["long_window"]
    position_size = params["position_size"]
    if (
        isinstance(short_window, bool)
        or not isinstance(short_window, int)
        or isinstance(long_window, bool)
        or not isinstance(long_window, int)
    ):
        raise ValueError("dual_ma window parameters must be integers")
    if not (1 <= short_window < long_window <= 10000):
        raise ValueError("dual_ma window parameters are invalid")
    if (
        isinstance(position_size, bool)
        or not isinstance(position_size, (int, float))
        or not math.isfinite(float(position_size))
        or not (0 < float(position_size) <= 1)
    ):
        raise ValueError("dual_ma position_size must be within (0, 1]")

    policy = plan.execution_policy
    if policy is None or policy.lag_bars < 1:
        raise ValueError("execution policy must enforce at least one-bar lag")
    frame.to_parquet(filtered_path, index=False)
    config = BacktestConfig(
        initial_cash=1_000_000.0,
        commission=float(policy.commission_bps) / 10_000.0,
        slippage_perc=float(policy.slippage_bps) / 10_000.0,
        metrics_profile="industrial",
        market_data_mode="source_path",
        source_path=str(filtered_path),
        symbol=str(plan.data_requests[0].symbols[0]),
        frequency=handler.frequency,
        strict_real_data=True,
        strict_temporal_validation=True,
        include_trade_ledger=True,
        include_data_fingerprint=True,
        allow_short=False,
    )
    report = run_single_asset_backtest(
        config=config,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        strategy_params=params,
    )
    returns = report["returns"]
    period = (
        pd.Series(returns["period_return"], dtype=float)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    position = (
        pd.Series(returns["realized_position"], dtype=float)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    metrics = json_value(report["metrics"])
    summary = {
        "data_fingerprint": report["summary"].get("data_fingerprint"),
        "bars": int(report["summary"]["bars"]),
        "start": pd.Timestamp(report["summary"]["start"]).isoformat(),
        "end": pd.Timestamp(report["summary"]["end"]).isoformat(),
        "final_equity": float(report["summary"]["final_equity"]),
        "metrics": metrics,
        "tail_risk_var_99": abs(float(period.quantile(0.01))) if len(period) else None,
        "position_limit": float(position.abs().max()) if len(position) else None,
    }
    return summary, canonical_sha(summary)


def execute(
    plan_path: Path,
    catalog_path: Path,
    snapshot_root: Path,
    engine_root: Path,
    output: Path,
) -> None:
    plan = load_plan(plan_path)
    assert plan.adapter is not None
    handler = adapter_handler(plan.adapter.adapter_id)
    catalog = load_catalog(catalog_path)
    sandbox_checks, sandbox_proof = verify_sandbox(
        snapshot_root=snapshot_root,
        engine_root=engine_root,
        runtime_root=Path(sys.prefix),
    )
    actual_tree = source_tree_sha(engine_root, handler.source_tree)
    validate_catalog_bindings(plan=plan, catalog=catalog, handler=handler, actual_tree=actual_tree)
    frame, snapshot, snapshot_manifest_path = load_snapshot(snapshot_root, plan)
    output.mkdir(parents=True, exist_ok=False)
    first, first_hash = run_once(frame=frame, plan=plan, filtered_path=output / "oos-first.parquet")
    second, second_hash = run_once(
        frame=frame,
        plan=plan,
        filtered_path=output / "oos-second.parquet",
    )
    metrics = first["metrics"]
    risk_metrics = BacktestRiskMetrics(
        total_return=float(metrics["total_return"]),
        annual_return=float(metrics["annual_return"]),
        sharpe=float(metrics["sharpe"]),
        volatility=abs(float(metrics["volatility"])),
        max_drawdown=abs(float(metrics["max_drawdown"])),
        tail_risk_var_99=float(first["tail_risk_var_99"]),
        turnover=abs(float(metrics["turnover"])),
        trading_cost=abs(float(metrics["commission_paid"])) / 1_000_000.0,
        position_limit=float(first["position_limit"]),
        correlation_with_existing=None,
        capacity_estimate_usd=None,
    )
    missing = [
        "existing portfolio return series for correlation_with_existing",
        "ADV/participation/impact inputs for capacity_estimate_usd",
        (
            "PR_STRATEGY_SOURCE_NOT_EXECUTED: the v1 handler evaluates the catalog-pinned "
            "external engine built-in dual_ma, not pull-request strategy source"
        ),
    ]
    reproducible = first_hash == second_hash
    if not reproducible:
        missing.append(
            "NON_REPRODUCIBLE: independent backtest runs produced different canonical hashes"
        )
    evidence_payload = {
        "schema_version": 1,
        "binding": plan.binding.model_dump(mode="json"),
        "task_digest": plan.task_digest,
        "step_id": plan.step_id,
        "request_id": plan.request_id,
        "plan_digest": plan.plan_digest,
        "data_snapshot_digest": sha256_file(snapshot_manifest_path),
        "engine_digest": actual_tree,
        "policy_digest": canonical_sha(
            plan.execution_policy.model_dump(mode="json")  # type: ignore[union-attr]
        ),
        "status": EvidenceStatus.BLOCK,
        "data_objects": [
            DataObjectEvidence(
                logical_dataset=handler.logical_dataset,
                object_uri=f"snapshot://{snapshot['snapshot_id']}/ohlcv.parquet",
                content_sha256=snapshot["normalized_content_sha256"],
                schema_sha256=sha256_file(snapshot_manifest_path),
                rows=int(snapshot["rows"]),
                start_date=pd.Timestamp(snapshot["start"]).date(),
                end_date=pd.Timestamp(snapshot["end"]).date(),
            ).model_dump(mode="json")
        ],
        "temporal_checks": {
            "strict_timestamp": True,
            "non_overlapping_oos": True,
            "next_bar_fill": True,
            "double_run_reproducible": reproducible,
        },
        "cost_checks": {
            "commission_nonzero": (
                plan.execution_policy.commission_bps > 0  # type: ignore[union-attr]
            ),
            "slippage_nonzero": plan.execution_policy.slippage_bps > 0,  # type: ignore[union-attr]
        },
        "sandbox_checks": sandbox_checks,
        "reproducibility_hashes": [first_hash, second_hash],
        "metrics": risk_metrics.model_dump(mode="json"),
        "missing_evidence": missing,
    }
    evidence = BacktestEvidence(
        **evidence_payload,
        artifact_sha256=canonical_sha(evidence_payload),
    )
    result = {
        "evidence": evidence.model_dump(mode="json"),
        "backtest_summary": first,
        "sandbox_proof": sandbox_proof,
        "snapshot_id": snapshot["snapshot_id"],
    }
    encoded = json.dumps(json_value(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("agentic backtest artifact exceeds 1 MiB")
    artifact = output / "backtest-evidence.json"
    artifact.write_text(encoded, encoding="utf-8")
    (output / "backtest-evidence.sha256").write_text(f"{sha256_file(artifact)}  {artifact.name}\n")
    print(json.dumps(json_value(result), ensure_ascii=False, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one trusted agent-planned backtest.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--snapshot-root", required=True)
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    execute(
        Path(args.plan).resolve(),
        Path(args.catalog).resolve(),
        Path(args.snapshot_root).resolve(),
        Path(args.engine_root).resolve(),
        Path(args.output).resolve(),
    )


if __name__ == "__main__":
    main()
