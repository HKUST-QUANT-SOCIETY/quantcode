"""Trusted-boundary tests for the agent-planned real backtest executor.

These tests intentionally use a tiny local immutable snapshot and a fake
backtest runtime.  They exercise the trusted plan/catalog/snapshot boundary;
they do not make an investment-performance claim.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from schemas.risk_gate_artifact import (
    BacktestAdapter,
    BacktestWindow,
    DataRequest,
    ExecutionPolicy,
    PRBinding,
    RiskApplicability,
    RiskGatePlan,
    RiskGatePlanDraft,
    RiskSubject,
    RiskSubjectKind,
)
from scripts.ci import run_agentic_backtest as executor


BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
OTHER_SHA = "f" * 64


def test_executor_schema_has_python_310_enum_and_self_fallbacks() -> None:
    source = (Path(__file__).resolve().parents[1] / "schemas" / "_compat.py").read_text(
        encoding="utf-8"
    )
    assert "class StrEnum(str, Enum)" in source
    assert "from typing_extensions import Self" in source


def _engine_tree(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "engine"
    source = root / "backtest_layer" / "single_asset_backtest"
    source.mkdir(parents=True)
    (source / "config.py").write_text("class BacktestConfig: pass\n", encoding="utf-8")
    (source / "runner.py").write_text("def run_single_asset_backtest(): pass\n", encoding="utf-8")
    return root, executor.source_tree_sha(root, "backtest_layer/single_asset_backtest")


def _binding() -> PRBinding:
    return PRBinding(
        repository="HKUST-QUANT-SOCIETY/quantcode",
        pr_number=137,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
    )


def _plan(
    engine_digest: str,
    *,
    adapter_id: str = executor.SUPPORTED_ADAPTER,
    code_blob_sha256: str | None = None,
    parameters: dict[str, Any] | None = None,
    request_start: date = date(2020, 1, 1),
    request_end: date = date(2020, 1, 2),
    oos_start: date = date(2020, 1, 1),
    oos_end: date = date(2020, 1, 2),
    fields: list[str] | None = None,
) -> RiskGatePlan:
    draft = RiskGatePlanDraft(
        binding=_binding(),
        applicability=RiskApplicability.EVALUABLE,
        subjects=[
            RiskSubject(
                kind=RiskSubjectKind.STRATEGY,
                identifier="head-bound-dual-ma-rb",
                changed_files=["strategies/rb/backtest_manifest.json"],
                backtest_manifest_path="strategies/rb/backtest_manifest.json",
            )
        ],
        data_requests=[
            DataRequest(
                logical_dataset=executor.SUPPORTED_DATASET,
                fields=fields or ["timestamp", "open", "high", "low", "close", "volume"],
                start_date=request_start,
                end_date=request_end,
                symbols=["rb"],
                purpose="Head-bound out-of-sample risk evaluation",
                require_immutable_snapshot=True,
            )
        ],
        adapter=BacktestAdapter(
            adapter_id=adapter_id,
            entrypoint="single_asset_backtest.runner:run_single_asset_backtest",
            code_blob_sha256=code_blob_sha256 or engine_digest,
            engine_id="quantsociety_backend@test-commit",
            engine_digest=engine_digest,
        ),
        adapter_parameters=parameters
        or {
            "strategy_name": "dual_ma",
            "strategy_version": "1.0",
            "short_window": 3,
            "long_window": 8,
            "position_size": 0.75,
        },
        window=BacktestWindow(
            train_start=date(2019, 1, 1),
            train_end=date(2019, 12, 31),
            oos_start=oos_start,
            oos_end=oos_end,
        ),
        execution_policy=ExecutionPolicy(
            policy_id="cta-1m-v1",
            observation_time="bar close",
            signal_time="after bar close",
            fill_time="next bar open",
            lag_bars=1,
            commission_bps=1.0,
            slippage_bps=2.0,
            stamp_duty_bps=0.0,
            enforce_suspension=False,
            enforce_price_limits=False,
            enforce_t_plus_one=False,
        ),
        risk_policy_id="quant-risk-v1",
        rationale="The changed manifest declares an approved adapter and immutable OOS request.",
        planner_model="test-risk-scope-subagent",
        prompt_digest="a" * 64,
    )
    return RiskGatePlan.finalize(draft)


def _refinalize(plan: RiskGatePlan, mutate: Callable[[dict[str, Any]], None]) -> RiskGatePlan:
    payload = plan.model_dump(mode="json")
    payload.pop("plan_digest")
    mutate(payload)
    return RiskGatePlan.finalize(RiskGatePlanDraft.model_validate(payload))


def _write_plan(path: Path, plan: RiskGatePlan) -> Path:
    path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _write_catalog(path: Path, plan: RiskGatePlan, **adapter_overrides: Any) -> Path:
    assert plan.adapter is not None
    adapter = {
        "entrypoint": plan.adapter.entrypoint,
        "code_blob_sha256": plan.adapter.code_blob_sha256,
        "engine_id": plan.adapter.engine_id,
        "engine_digest": plan.adapter.engine_digest,
        "input_contract": "single_asset_ohlcv_and_strategy_adapter_v1",
        "execution_zone": "dedicated-risk-backtest",
    }
    adapter.update(adapter_overrides)
    payload = {
        "schema_version": 1,
        "risk_policies": {
            "quant-risk-v1": {
                "required_metrics": [
                    "sharpe",
                    "volatility",
                    "max_drawdown",
                    "tail_risk_var_99",
                    "turnover",
                    "trading_cost",
                    "position_limit",
                    "correlation_with_existing",
                    "capacity_estimate_usd",
                ]
            }
        },
        "adapters": {plan.adapter.adapter_id: adapter},
        "datasets": {
            executor.SUPPORTED_DATASET: {
                "catalog_only": False,
                "execution_zone": "server-b-shared-readonly",
                "fields": ["timestamp", "symbol", "open", "high", "low", "close", "volume"],
                "frequency": "1min",
                "immutable_identity": "content_sha256",
            }
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _snapshot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2020-01-01T09:00:00",
                    "2020-01-01T09:01:00",
                    "2020-01-02T09:00:00",
                    "2020-01-02T09:01:00",
                ]
            ),
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [10.0, 11.0, 12.0, 13.0],
        }
    )


def _write_snapshot(
    root: Path,
    *,
    frame: pd.DataFrame | None = None,
    manifest_overrides: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    root.mkdir()
    materialized = (frame if frame is not None else _snapshot_frame()).copy()
    data_path = root / "ohlcv.parquet"
    materialized.to_parquet(data_path, index=False)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "logical_dataset": executor.SUPPORTED_DATASET,
        "snapshot_id": executor.EXPECTED_SNAPSHOT_ID,
        "dataset_id": executor.EXPECTED_DATASET_ID,
        "normalized_content_sha256": executor.sha256_file(data_path),
        "rows": len(materialized),
        "symbol": "rb",
        "frequency": "1min",
        "start": pd.Timestamp(materialized["timestamp"].min()).isoformat(),
        "end": pd.Timestamp(materialized["timestamp"].max()).isoformat(),
        "columns": list(materialized.columns),
        "immutable": True,
    }
    manifest.update(manifest_overrides or {})
    (root / "snapshot-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root, manifest


def _summary(*, marker: str = "same") -> dict[str, Any]:
    return {
        "data_fingerprint": f"fingerprint-{marker}",
        "bars": 4,
        "start": "2020-01-01T09:00:00",
        "end": "2020-01-02T09:01:00",
        "final_equity": 900_000.0,
        "metrics": {
            "total_return": -0.10,
            "annual_return": -0.12,
            "sharpe": -1.2,
            "volatility": 0.20,
            "max_drawdown": -0.15,
            "turnover": 8.0,
            "commission_paid": 1_250.0,
            # The upstream engine historically emitted fabricated-looking zeros.
            # The trusted executor must not reinterpret them as correlation/capacity.
            "beta": 0.0,
            "capacity_estimate": 0.0,
        },
        "tail_risk_var_99": 0.03,
        "position_limit": 0.75,
    }


def _execute_with_fake_runs(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan: RiskGatePlan,
    engine_root: Path,
    snapshot_root: Path,
    run_results: list[tuple[dict[str, Any], str]] | None = None,
    catalog_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    plan_path = _write_plan(tmp_path / "risk-gate-plan.json", plan)
    catalog_path = _write_catalog(
        tmp_path / "catalog.yaml",
        plan,
        **(catalog_overrides or {}),
    )
    output = tmp_path / "result"
    result_sequence = iter(
        run_results
        or [
            (_summary(), executor.canonical_sha(_summary())),
            (_summary(), executor.canonical_sha(_summary())),
        ]
    )
    filtered_paths: list[Path] = []

    def fake_run_once(**kwargs: Any) -> tuple[dict[str, Any], str]:
        filtered_paths.append(kwargs["filtered_path"])
        return next(result_sequence)

    monkeypatch.setattr(executor, "run_once", fake_run_once)
    monkeypatch.setattr(
        executor,
        "verify_sandbox",
        lambda **kwargs: (
            {
                "network_disabled": True,
                "raw_data_read_only": True,
                "engine_read_only": True,
                "runtime_read_only": True,
                "pr_strategy_source_bound": False,
            },
            {
                "current_network_namespace": "net:[2]",
                "host_network_namespace": "net:[1]",
            },
        ),
    )
    executor.execute(plan_path, catalog_path, snapshot_root, engine_root, output)
    result = json.loads((output / "backtest-evidence.json").read_text(encoding="utf-8"))
    return result, filtered_paths


def _install_fake_backtest_runtime(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    package = types.ModuleType("single_asset_backtest")
    package.__path__ = []  # type: ignore[attr-defined]
    config_module = types.ModuleType("single_asset_backtest.config")
    runner_module = types.ModuleType("single_asset_backtest.runner")

    class FakeBacktestConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured["config"] = kwargs

    def fake_backtest(**kwargs: Any) -> dict[str, Any]:
        captured["call"] = kwargs
        return {
            "returns": {
                "period_return": [0.0, -0.01, 0.02],
                "realized_position": [0.0, 0.75, 0.75],
            },
            "metrics": {
                "total_return": 0.01,
                "annual_return": 0.02,
                "sharpe": 0.3,
                "volatility": 0.1,
                "max_drawdown": -0.02,
                "turnover": 1.5,
                "commission_paid": 50.0,
            },
            "summary": {
                "data_fingerprint": "fake-fingerprint",
                "bars": 3,
                "start": "2020-01-01T09:00:00",
                "end": "2020-01-02T09:00:00",
                "final_equity": 1_010_000.0,
            },
        }

    config_module.BacktestConfig = FakeBacktestConfig  # type: ignore[attr-defined]
    runner_module.run_single_asset_backtest = fake_backtest  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "single_asset_backtest", package)
    monkeypatch.setitem(sys.modules, "single_asset_backtest.config", config_module)
    monkeypatch.setitem(sys.modules, "single_asset_backtest.runner", runner_module)
    return captured


def test_execute_consumes_dynamic_plan_and_blocks_missing_risk_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_root, engine_digest = _engine_tree(tmp_path)
    plan = _plan(engine_digest)
    snapshot_root, snapshot = _write_snapshot(tmp_path / "snapshot")

    result, filtered_paths = _execute_with_fake_runs(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan=plan,
        engine_root=engine_root,
        snapshot_root=snapshot_root,
    )

    evidence = result["evidence"]
    assert evidence["binding"] == plan.binding.model_dump(mode="json")
    assert evidence["plan_digest"] == plan.plan_digest
    assert evidence["engine_digest"] == engine_digest
    evidence_without_digest = dict(evidence)
    artifact_digest = evidence_without_digest.pop("artifact_sha256")
    assert artifact_digest == executor.canonical_sha(evidence_without_digest)
    assert evidence["data_snapshot_digest"] == executor.sha256_file(
        snapshot_root / "snapshot-manifest.json"
    )
    assert evidence["policy_digest"] == executor.canonical_sha(
        plan.execution_policy.model_dump(mode="json")
    )
    assert evidence["data_objects"][0]["content_sha256"] == snapshot["normalized_content_sha256"]
    assert evidence["reproducibility_hashes"][0] == evidence["reproducibility_hashes"][1]
    assert filtered_paths == [
        tmp_path / "result" / "oos-first.parquet",
        tmp_path / "result" / "oos-second.parquet",
    ]

    assert evidence["status"] == "block"
    assert evidence["metrics"]["correlation_with_existing"] is None
    assert evidence["metrics"]["capacity_estimate_usd"] is None
    assert any("correlation" in item for item in evidence["missing_evidence"])
    assert any("capacity" in item for item in evidence["missing_evidence"])
    assert any("PR_STRATEGY_SOURCE_NOT_EXECUTED" in item for item in evidence["missing_evidence"])
    assert evidence["sandbox_checks"]["pr_strategy_source_bound"] is False
    assert "pass" not in {evidence["status"]}
    artifact = tmp_path / "result" / "backtest-evidence.json"
    sidecar_digest = (tmp_path / "result" / "backtest-evidence.sha256").read_text().split()[0]
    assert sidecar_digest == executor.sha256_file(artifact)


def test_run_once_uses_only_approved_plan_parameters_and_nonzero_costs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_backtest_runtime(monkeypatch)
    plan = _plan("a" * 64)

    summary, digest = executor.run_once(
        frame=_snapshot_frame(),
        plan=plan,
        filtered_path=tmp_path / "filtered.parquet",
    )

    assert len(digest) == 64
    assert summary["tail_risk_var_99"] == pytest.approx(0.0098)
    assert summary["position_limit"] == pytest.approx(0.75)
    assert captured["call"]["strategy_name"] == "dual_ma"
    assert captured["call"]["strategy_version"] == "1.0"
    assert captured["call"]["strategy_params"] == {
        "short_window": 3,
        "long_window": 8,
        "position_size": 0.75,
    }
    assert captured["config"]["commission"] == pytest.approx(0.0001)
    assert captured["config"]["slippage_perc"] == pytest.approx(0.0002)
    assert captured["config"]["strict_real_data"] is True
    assert captured["config"]["strict_temporal_validation"] is True


@pytest.mark.parametrize(
    ("parameters", "error"),
    [
        (
            {
                "strategy_name": "dual_ma",
                "strategy_version": "1.0",
                "short_window": 3,
                "long_window": 8,
                "position_size": 0.75,
                "shell": "curl attacker.invalid",
            },
            "unapproved keys",
        ),
        (
            {
                "strategy_name": "not_registered",
                "strategy_version": "1.0",
                "short_window": 3,
                "long_window": 8,
                "position_size": 0.75,
            },
            "allows only strategy dual_ma",
        ),
        (
            {
                "strategy_name": "dual_ma",
                "strategy_version": "9.9",
                "short_window": 3,
                "long_window": 8,
                "position_size": 0.75,
            },
            "strategy version",
        ),
        (
            {
                "strategy_name": "dual_ma",
                "strategy_version": "1.0",
                "short_window": 9,
                "long_window": 8,
                "position_size": 0.75,
            },
            "window parameters",
        ),
        (
            {
                "strategy_name": "dual_ma",
                "strategy_version": "1.0",
                "short_window": 3,
                "long_window": 8,
                "position_size": 0.0,
            },
            "position_size",
        ),
        (
            {
                "strategy_name": "dual_ma",
                "strategy_version": "1.0",
                "short_window": True,
                "long_window": 8,
                "position_size": 0.75,
            },
            "must be integers",
        ),
        (
            {
                "strategy_name": "dual_ma",
                "strategy_version": "1.0",
                "short_window": 3,
                "long_window": 8,
                "position_size": True,
            },
            "position_size",
        ),
    ],
)
def test_unknown_or_invalid_adapter_parameters_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parameters: dict[str, Any],
    error: str,
) -> None:
    _install_fake_backtest_runtime(monkeypatch)
    plan = _plan("a" * 64, parameters=parameters)

    with pytest.raises(ValueError, match=error):
        executor.run_once(
            frame=_snapshot_frame(),
            plan=plan,
            filtered_path=tmp_path / "must-not-exist.parquet",
        )


def test_tampered_plan_digest_is_rejected_before_execution(tmp_path: Path) -> None:
    plan = _plan("a" * 64)
    payload = plan.model_dump(mode="json")
    payload["adapter_parameters"]["short_window"] = 2
    path = tmp_path / "tampered-plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="plan_digest"):
        executor.load_plan(path)


def test_non_evaluable_plan_cannot_enter_the_executor(tmp_path: Path) -> None:
    draft = RiskGatePlanDraft(
        binding=_binding(),
        applicability=RiskApplicability.NOT_EVALUABLE,
        risk_policy_id="quant-risk-v1",
        rationale="No executable adapter contract was declared.",
        missing_requirements=["BacktestManifest"],
        planner_model="test-risk-scope-subagent",
        prompt_digest="a" * 64,
    )
    path = _write_plan(tmp_path / "not-evaluable.json", RiskGatePlan.finalize(draft))

    with pytest.raises(ValueError, match="requires evaluable plan"):
        executor.load_plan(path)


def test_unknown_adapter_fails_closed_even_if_a_plan_is_canonically_refinalized(
    tmp_path: Path,
) -> None:
    plan = _plan("a" * 64, adapter_id="arbitrary-shell-v1")
    path = _write_plan(tmp_path / "unknown-adapter.json", plan)

    with pytest.raises(ValueError, match="supports|approved|adapter"):
        executor.load_plan(path)


@pytest.mark.parametrize(
    ("target", "field", "replacement"),
    [
        ("plan", "code_blob_sha256", OTHER_SHA),
        ("catalog", "code_blob_sha256", OTHER_SHA),
        ("catalog", "entrypoint", "attacker.module:run"),
        ("catalog", "engine_id", "unapproved-engine@deadbeef"),
    ],
)
def test_plan_catalog_and_engine_adapter_identity_must_match_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    field: str,
    replacement: str,
) -> None:
    engine_root, engine_digest = _engine_tree(tmp_path)
    plan = _plan(engine_digest)
    catalog_overrides: dict[str, Any] = {}
    if target == "plan":
        plan = _refinalize(plan, lambda payload: payload["adapter"].__setitem__(field, replacement))
    else:
        catalog_overrides[field] = replacement
    snapshot_root, _ = _write_snapshot(tmp_path / "snapshot")

    with pytest.raises(ValueError, match="adapter|hash|identity|engine"):
        _execute_with_fake_runs(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            plan=plan,
            engine_root=engine_root,
            snapshot_root=snapshot_root,
            catalog_overrides=catalog_overrides,
        )


def test_changed_engine_tree_is_rejected_after_plan_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_root, engine_digest = _engine_tree(tmp_path)
    plan = _plan(engine_digest)
    snapshot_root, _ = _write_snapshot(tmp_path / "snapshot")
    source = engine_root / "backtest_layer" / "single_asset_backtest" / "runner.py"
    source.write_text("def run_single_asset_backtest(): return 'tampered'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tree hash|engine|hash"):
        _execute_with_fake_runs(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            plan=plan,
            engine_root=engine_root,
            snapshot_root=snapshot_root,
        )


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"immutable": False}, "mutable|immutable"),
        ({"snapshot_id": "different-snapshot"}, "snapshot"),
        ({"logical_dataset": "unapproved-dataset"}, "dataset|snapshot"),
        ({"symbol": "au"}, "symbol|snapshot"),
        ({"frequency": "1d"}, "frequency|snapshot"),
        ({"rows": 999}, "row|snapshot"),
        ({"start": "2019-12-31T09:00:00"}, "time range|snapshot"),
        ({"columns": ["timestamp", "close"]}, "columns|snapshot"),
    ],
)
def test_snapshot_manifest_identity_is_fully_bound_and_fail_closed(
    tmp_path: Path,
    overrides: dict[str, Any],
    error: str,
) -> None:
    plan = _plan("a" * 64)
    snapshot_root, _ = _write_snapshot(
        tmp_path / "snapshot",
        manifest_overrides=overrides,
    )

    with pytest.raises(ValueError, match=error):
        executor.load_snapshot(snapshot_root, plan)


def test_snapshot_content_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    plan = _plan("a" * 64)
    snapshot_root, _ = _write_snapshot(tmp_path / "snapshot")
    data_path = snapshot_root / "ohlcv.parquet"
    tampered = _snapshot_frame()
    tampered.loc[0, "close"] = 999_999.0
    tampered.to_parquet(data_path, index=False)

    with pytest.raises(ValueError, match="content hash"):
        executor.load_snapshot(snapshot_root, plan)


def test_partial_oos_snapshot_is_rejected_instead_of_silently_shortening_window(
    tmp_path: Path,
) -> None:
    plan = _plan(
        "a" * 64,
        request_end=date(2020, 1, 3),
        oos_end=date(2020, 1, 3),
    )
    snapshot_root, _ = _write_snapshot(tmp_path / "snapshot")

    with pytest.raises(ValueError, match="cover|OOS|window"):
        executor.load_snapshot(snapshot_root, plan)


def test_data_request_must_use_only_catalog_approved_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_root, engine_digest = _engine_tree(tmp_path)
    plan = _plan(
        engine_digest,
        fields=["timestamp", "open", "high", "low", "close", "volume", "future_return"],
    )
    snapshot_root, _ = _write_snapshot(tmp_path / "snapshot")

    with pytest.raises(ValueError, match="field|dataset|approved"):
        _execute_with_fake_runs(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            plan=plan,
            engine_root=engine_root,
            snapshot_root=snapshot_root,
        )


def test_data_request_must_exactly_match_the_declared_oos_window(tmp_path: Path) -> None:
    plan = _plan(
        "a" * 64,
        request_start=date(2020, 1, 2),
        request_end=date(2020, 1, 2),
        oos_start=date(2020, 1, 1),
        oos_end=date(2020, 1, 2),
    )
    path = _write_plan(tmp_path / "window-mismatch.json", plan)

    with pytest.raises(ValueError, match="exactly match"):
        executor.load_plan(path)


def test_zero_cost_or_same_bar_policy_is_rejected(tmp_path: Path) -> None:
    plan = _plan("a" * 64)
    zero_cost = _refinalize(
        plan,
        lambda payload: payload["execution_policy"].update(
            {"fill_time": "same bar close", "commission_bps": 0.0}
        ),
    )
    path = _write_plan(tmp_path / "bad-policy.json", zero_cost)

    with pytest.raises(ValueError, match="next-open|non-zero costs|policy"):
        executor.load_plan(path)


def test_policy_cannot_claim_controls_the_handler_does_not_implement(tmp_path: Path) -> None:
    plan = _plan("a" * 64)
    unsupported_controls = _refinalize(
        plan,
        lambda payload: payload["execution_policy"].update(
            {
                "stamp_duty_bps": 5.0,
                "enforce_suspension": True,
                "enforce_price_limits": True,
                "enforce_t_plus_one": True,
            }
        ),
    )
    path = _write_plan(tmp_path / "unsupported-controls.json", unsupported_controls)

    with pytest.raises(ValueError, match="controls implemented by the CTA handler"):
        executor.load_plan(path)


def test_non_reproducible_double_run_is_explicitly_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine_root, engine_digest = _engine_tree(tmp_path)
    plan = _plan(engine_digest)
    snapshot_root, _ = _write_snapshot(tmp_path / "snapshot")
    first = _summary(marker="first")
    second = _summary(marker="second")

    result, _ = _execute_with_fake_runs(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan=plan,
        engine_root=engine_root,
        snapshot_root=snapshot_root,
        run_results=[
            (first, executor.canonical_sha(first)),
            (second, executor.canonical_sha(second)),
        ],
    )

    evidence = result["evidence"]
    assert evidence["status"] == "block"
    assert len(set(evidence["reproducibility_hashes"])) == 2
    assert any("NON_REPRODUCIBLE" in item for item in evidence["missing_evidence"])
    assert evidence["metrics"]["correlation_with_existing"] is None
    assert evidence["metrics"]["capacity_estimate_usd"] is None


def test_source_tree_digest_is_order_stable_but_content_sensitive(tmp_path: Path) -> None:
    root, digest = _engine_tree(tmp_path)
    source = root / "backtest_layer" / "single_asset_backtest"
    (source / "aaa.py").write_text("VALUE = 1\n", encoding="utf-8")
    with_extra = executor.source_tree_sha(root, "backtest_layer/single_asset_backtest")
    assert with_extra != digest

    (source / "aaa.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert executor.source_tree_sha(root, "backtest_layer/single_asset_backtest") != with_extra


def test_sandbox_proof_requires_a_distinct_network_namespace_and_readonly_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = [tmp_path / name for name in ("snapshot", "engine", "runtime")]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(
        executor.os,
        "readlink",
        lambda path: "net:[2]" if path == "/proc/self/ns/net" else "net:[1]",
    )
    monkeypatch.setattr(executor, "_mount_options", lambda path: {"ro", "nodev"})

    checks, proof = executor.verify_sandbox(
        snapshot_root=roots[0],
        engine_root=roots[1],
        runtime_root=roots[2],
    )

    assert checks["network_disabled"] is True
    assert checks["raw_data_read_only"] is True
    assert checks["pr_strategy_source_bound"] is False
    assert proof == {
        "current_network_namespace": "net:[2]",
        "host_network_namespace": "net:[1]",
    }


def test_sandbox_proof_rejects_host_network_or_writable_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = [tmp_path / name for name in ("snapshot", "engine", "runtime")]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(executor.os, "readlink", lambda path: "net:[1]")
    with pytest.raises(ValueError, match="distinct network namespace"):
        executor.verify_sandbox(
            snapshot_root=roots[0],
            engine_root=roots[1],
            runtime_root=roots[2],
        )

    monkeypatch.setattr(
        executor.os,
        "readlink",
        lambda path: "net:[2]" if path == "/proc/self/ns/net" else "net:[1]",
    )
    monkeypatch.setattr(
        executor,
        "_mount_options",
        lambda path: {"rw"} if path == roots[0] else {"ro"},
    )
    with pytest.raises(ValueError, match="not mounted read-only"):
        executor.verify_sandbox(
            snapshot_root=roots[0],
            engine_root=roots[1],
            runtime_root=roots[2],
        )
