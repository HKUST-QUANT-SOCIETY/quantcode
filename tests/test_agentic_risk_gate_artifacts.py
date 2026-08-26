"""Contracts for dynamic subagent planning and evidence-backed Risk Gate decisions."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from schemas.risk_gate_artifact import (
    AgenticRiskGateVerdict,
    BacktestAdapter,
    BacktestEvidence,
    BacktestRiskMetrics,
    BacktestWindow,
    DataRequest,
    EvidenceStatus,
    ExecutionPolicy,
    HumanGateEvidenceBinding,
    PRBinding,
    RiskApplicability,
    RiskFinding,
    RiskGateArtifact,
    RiskGatePlan,
    RiskGatePlanDraft,
    RiskSubject,
    RiskSubjectKind,
)


SHA = "a" * 64
OTHER_SHA = "b" * 64
BINDING = PRBinding(
    repository="HKUST-QUANT-SOCIETY/quantcode",
    pr_number=35,
    base_sha="1" * 40,
    head_sha="2" * 40,
)


def _evaluable_draft() -> RiskGatePlanDraft:
    return RiskGatePlanDraft(
        binding=BINDING,
        applicability=RiskApplicability.EVALUABLE,
        subjects=[
            RiskSubject(
                kind=RiskSubjectKind.STRATEGY,
                identifier="dual-ma-rb",
                changed_files=["strategies/dual_ma.py"],
                backtest_manifest_path="backtest.yaml",
            )
        ],
        data_requests=[
            DataRequest(
                logical_dataset="cta/rb/1m",
                fields=["timestamp", "open", "high", "low", "close", "volume"],
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 31),
                symbols=["rb"],
                purpose="Out-of-sample strategy risk evaluation",
            )
        ],
        adapter=BacktestAdapter(
            adapter_id="single-asset-backtrader-v1",
            entrypoint="backtest_layer.single_asset_backtest",
            code_blob_sha256=SHA,
            engine_id="quantsociety-backtest",
            engine_digest=OTHER_SHA,
        ),
        adapter_parameters={
            "strategy_name": "dual_ma",
            "short_window": 20,
            "long_window": 100,
            "position_size": 1.0,
        },
        window=BacktestWindow(
            train_start=date(2018, 1, 1),
            train_end=date(2019, 6, 30),
            validation_start=date(2019, 7, 1),
            validation_end=date(2019, 12, 31),
            oos_start=date(2020, 1, 1),
            oos_end=date(2020, 12, 31),
        ),
        execution_policy=ExecutionPolicy(
            policy_id="cta-1m-v1",
            observation_time="bar close",
            signal_time="bar close after observation",
            fill_time="next bar open",
            lag_bars=1,
            commission_bps=1.0,
            slippage_bps=1.0,
            stamp_duty_bps=0.0,
            enforce_t_plus_one=False,
        ),
        risk_policy_id="quant-risk-v1",
        rationale="Strategy code and a backtest manifest changed.",
        planner_model="deepseek-risk-planner",
        prompt_digest=SHA,
    )


def test_planner_can_return_not_applicable_without_execution() -> None:
    draft = RiskGatePlanDraft(
        binding=BINDING,
        applicability=RiskApplicability.NOT_APPLICABLE,
        risk_policy_id="quant-risk-v1",
        rationale="Documentation-only change has no strategy or portfolio effect.",
        planner_model="deepseek-risk-planner",
        prompt_digest=SHA,
    )
    plan = RiskGatePlan.finalize(draft)
    assert plan.applicability == RiskApplicability.NOT_APPLICABLE
    assert len(plan.plan_digest) == 64


def test_evaluable_plan_is_canonical_and_tamper_evident() -> None:
    plan = RiskGatePlan.finalize(_evaluable_draft())
    payload = plan.model_dump(mode="json")
    payload["rationale"] = "tampered"
    with pytest.raises(ValidationError, match="plan_digest"):
        RiskGatePlan.model_validate(payload)


def test_evaluable_plan_requires_adapter_data_and_execution_policy() -> None:
    payload = _evaluable_draft().model_dump()
    payload["adapter"] = None
    with pytest.raises(ValidationError, match="requires subjects, data, adapter, and window"):
        RiskGatePlanDraft.model_validate(payload)


def test_not_evaluable_plan_must_explain_missing_contract() -> None:
    with pytest.raises(ValidationError, match="missing requirements"):
        RiskGatePlanDraft(
            binding=BINDING,
            applicability=RiskApplicability.NOT_EVALUABLE,
            risk_policy_id="quant-risk-v1",
            rationale="Model Python has no declared entrypoint or return artifact.",
            planner_model="deepseek-risk-planner",
            prompt_digest=SHA,
        )


def test_backtest_windows_must_be_non_overlapping() -> None:
    with pytest.raises(ValidationError, match="OOS window must start after"):
        BacktestWindow(
            train_start=date(2020, 1, 1),
            train_end=date(2020, 12, 31),
            oos_start=date(2020, 12, 1),
            oos_end=date(2021, 12, 31),
        )


def _complete_metrics() -> BacktestRiskMetrics:
    return BacktestRiskMetrics(
        total_return=0.1,
        annual_return=0.08,
        sharpe=1.1,
        volatility=0.15,
        max_drawdown=0.12,
        tail_risk_var_99=0.025,
        turnover=1.2,
        trading_cost=0.01,
        position_limit=0.05,
        correlation_with_existing=0.3,
        capacity_estimate_usd=10_000_000,
    )


def test_passing_evidence_requires_complete_metrics_and_repeatability() -> None:
    evidence = BacktestEvidence(
        binding=BINDING,
        plan_digest=SHA,
        data_snapshot_digest=OTHER_SHA,
        engine_digest=SHA,
        policy_digest=OTHER_SHA,
        status=EvidenceStatus.PASS,
        temporal_checks={"pit": True, "next_bar_fill": True},
        cost_checks={"fees": True, "slippage": True},
        sandbox_checks={"network_disabled": True},
        reproducibility_hashes=[SHA, SHA],
        metrics=_complete_metrics(),
        artifact_sha256=OTHER_SHA,
    )
    assert evidence.status == EvidenceStatus.PASS

    payload = evidence.model_dump()
    payload["metrics"]["correlation_with_existing"] = None
    with pytest.raises(ValidationError, match="cannot omit required risk metrics"):
        BacktestEvidence.model_validate(payload)

    payload = evidence.model_dump()
    payload["reproducibility_hashes"] = [SHA, OTHER_SHA]
    with pytest.raises(ValidationError, match="two identical"):
        BacktestEvidence.model_validate(payload)


def test_real_executor_probe_with_missing_correlation_cannot_pass() -> None:
    with pytest.raises(ValidationError, match="cannot omit required risk metrics"):
        BacktestEvidence(
            binding=BINDING,
            plan_digest=SHA,
            data_snapshot_digest=OTHER_SHA,
            engine_digest=SHA,
            policy_digest=OTHER_SHA,
            status=EvidenceStatus.PASS,
            temporal_checks={"strict_timestamp": True, "next_bar_fill": True},
            cost_checks={"commission": True, "slippage": True},
            sandbox_checks={"network_disabled": True},
            reproducibility_hashes=[SHA, SHA],
            metrics=BacktestRiskMetrics(
                total_return=-0.7406258184617642,
                annual_return=-0.6245369205749354,
                sharpe=-6.910257923626453,
                volatility=0.09037823587446978,
                max_drawdown=0.7464468916716153,
                tail_risk_var_99=0.00044271152099262245,
                turnover=6663.44506020242,
                trading_cost=364510.67379108776,
                position_limit=0.9999972682856246,
                correlation_with_existing=None,
                capacity_estimate_usd=None,
            ),
            artifact_sha256=OTHER_SHA,
        )


def test_human_gate_only_accepts_overridable_risk_preference_findings() -> None:
    artifact = RiskGateArtifact(
        binding=BINDING,
        plan_digest=SHA,
        evidence_digest=OTHER_SHA,
        policy_digest=SHA,
        verdict=AgenticRiskGateVerdict.NEEDS_HUMAN,
        findings=[
            RiskFinding(
                code="MAX_DRAWDOWN",
                severity="blocker",
                message="Validated OOS drawdown exceeds the risk appetite threshold.",
                overridable=True,
            )
        ],
        human_gate_allowed=True,
        artifact_sha256=OTHER_SHA,
    )
    assert artifact.human_gate_allowed is True

    payload = artifact.model_dump()
    payload["findings"][0]["overridable"] = False
    with pytest.raises(ValidationError, match="cannot enter HumanGate"):
        RiskGateArtifact.model_validate(payload)


def test_not_evaluable_artifact_is_fail_closed_and_not_overridable() -> None:
    artifact = RiskGateArtifact(
        binding=BINDING,
        plan_digest=SHA,
        evidence_digest=OTHER_SHA,
        policy_digest=SHA,
        verdict=AgenticRiskGateVerdict.NOT_EVALUABLE,
        missing_evidence=["BacktestManifest with executable adapter and data bindings"],
        human_gate_allowed=False,
        artifact_sha256=OTHER_SHA,
    )
    assert artifact.verdict == AgenticRiskGateVerdict.NOT_EVALUABLE


def test_not_applicable_artifact_is_clean_no_execution_result() -> None:
    artifact = RiskGateArtifact(
        binding=BINDING,
        task_digest=SHA,
        plan_digest=OTHER_SHA,
        evidence_digest=SHA,
        policy_digest=OTHER_SHA,
        verdict=AgenticRiskGateVerdict.NOT_APPLICABLE,
        artifact_sha256=OTHER_SHA,
    )
    assert artifact.completed_step_ids == []

    payload = artifact.model_dump()
    payload["findings"] = [
        {
            "code": "SHOULD_NOT_PASS",
            "severity": "blocker",
            "message": "unexpected finding",
            "overridable": False,
        }
    ]
    with pytest.raises(ValidationError, match="not_applicable cannot contain"):
        RiskGateArtifact.model_validate(payload)


def test_human_gate_decision_binds_task_plan_evidence_and_final_artifact() -> None:
    decision = HumanGateEvidenceBinding(
        binding=BINDING,
        task_digest=SHA,
        plan_digest=OTHER_SHA,
        evidence_digest=SHA,
        policy_digest=OTHER_SHA,
        risk_artifact_digest=SHA,
        decision="approve",
        decided_by="risk-owner",
        reason="Reviewed the explicit head-bound exception.",
        decided_at=datetime.now(timezone.utc),
    )
    assert decision.plan_digest == OTHER_SHA

    payload = decision.model_dump()
    payload["decided_at"] = datetime.now().replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone-aware"):
        HumanGateEvidenceBinding.model_validate(payload)
