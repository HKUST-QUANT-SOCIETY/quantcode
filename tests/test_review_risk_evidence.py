"""Trusted reduction of BacktestEvidence into canonical RiskGateArtifact."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas.risk_gate_artifact import (
    AgenticRiskGateVerdict,
    BacktestAdapter,
    BacktestEvidence,
    BacktestRiskMetrics,
    BacktestWindow,
    DataObjectEvidence,
    DataRequest,
    EvidenceStatus,
    ExecutionPolicy,
    PRBinding,
    RiskApplicability,
    RiskGatePlan,
    RiskGatePlanDraft,
    RiskSubject,
    RiskSubjectKind,
)
from schemas.risk_gate_task import (
    RiskGateCoverage,
    RiskGateEvidence,
    RiskGateExecutionRequest,
    RiskGateProcessStep,
    RiskGateReason,
    RiskGateScope,
    RiskGateScopeTarget,
    RiskGateSubagentProvenance,
    RiskGateTaskArtifact,
    RiskGateTaskDraft,
    RiskGateTrigger,
)
from scripts.ci.review_risk_evidence import (
    FindingDisposition,
    ReviewerProposal,
    RiskReviewPolicy,
    build_reviewer_context,
    canonical_evidence_digest,
    canonical_sha256,
    decision_policy_digest,
    load_evidence,
    load_policy,
    plan_proposal_projection,
    review_risk_evidence,
    review_plan_without_execution,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
BINDING = PRBinding(
    repository="HKUST-QUANT-SOCIETY/quantcode",
    pr_number=35,
    base_sha="1" * 40,
    head_sha="2" * 40,
)


def _plan() -> RiskGatePlan:
    draft = RiskGatePlanDraft(
        binding=BINDING,
        applicability=RiskApplicability.EVALUABLE,
        subjects=[
            RiskSubject(
                kind=RiskSubjectKind.STRATEGY,
                identifier="dual-ma-rb",
                changed_files=["strategies/dual_ma.py"],
                backtest_manifest_path="strategies/backtest_manifest.json",
            )
        ],
        data_requests=[
            DataRequest(
                logical_dataset="cta-benchmark-rb-1m",
                fields=["timestamp", "open", "high", "low", "close", "volume"],
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 31),
                symbols=["rb"],
                purpose="Out-of-sample strategy risk evaluation",
            )
        ],
        adapter=BacktestAdapter(
            adapter_id="single-asset-backtrader-v1",
            entrypoint="single_asset_backtest.runner:run_single_asset_backtest",
            code_blob_sha256=SHA_A,
            engine_id="quantsociety-backtest",
            engine_digest=SHA_B,
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
            signal_time="after bar close",
            fill_time="next bar open",
            lag_bars=1,
            commission_bps=1.0,
            slippage_bps=1.0,
            stamp_duty_bps=0.0,
            enforce_t_plus_one=False,
        ),
        risk_policy_id="quant-risk-v1",
        rationale="Strategy and executable backtest manifest changed.",
        planner_model="deepseek-risk-planner",
        prompt_digest=SHA_A,
    )
    return RiskGatePlan.finalize(draft)


def _policy() -> RiskReviewPolicy:
    return RiskReviewPolicy.model_validate(
        {
            "schema_version": 1,
            "policy_id": "quant-risk-v1",
            "required_temporal_checks": [
                "strict_timestamp",
                "non_overlapping_oos",
                "next_bar_fill",
            ],
            "required_cost_checks": ["commission_nonzero", "slippage_nonzero"],
            "required_sandbox_checks": ["network_disabled", "raw_data_read_only"],
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
            ],
            "thresholds": [
                {
                    "code": "MAX_DRAWDOWN",
                    "metric": "max_drawdown",
                    "comparator": "max",
                    "limit": 0.15,
                    "disposition": "needs_human",
                    "message": "Validated OOS drawdown exceeds the risk-appetite threshold.",
                },
                {
                    "code": "CORRELATION_LIMIT",
                    "metric": "correlation_with_existing",
                    "comparator": "abs_max",
                    "limit": 0.6,
                    "disposition": "block",
                    "message": "Portfolio correlation exceeds the diversification limit.",
                },
                {
                    "code": "CAPACITY_MINIMUM",
                    "metric": "capacity_estimate_usd",
                    "comparator": "min",
                    "limit": 1_000_000,
                    "disposition": "block",
                    "message": "Estimated executable capacity is below the policy minimum.",
                },
            ],
            "reviewer_finding_rules": [
                {"code": "REGIME_SENSITIVITY", "disposition": "needs_human"},
                {"code": "UNMODELLED_TAIL", "disposition": "block"},
            ],
        }
    )


def _metrics(**updates: float | None) -> BacktestRiskMetrics:
    payload = {
        "total_return": 0.10,
        "annual_return": 0.08,
        "sharpe": 1.10,
        "volatility": 0.15,
        "max_drawdown": 0.12,
        "tail_risk_var_99": 0.025,
        "turnover": 1.2,
        "trading_cost": 0.01,
        "position_limit": 0.05,
        "correlation_with_existing": 0.30,
        "capacity_estimate_usd": 10_000_000,
    }
    payload.update(updates)
    return BacktestRiskMetrics(**payload)


def _evidence(
    *,
    status: EvidenceStatus = EvidenceStatus.PASS,
    metrics: BacktestRiskMetrics | None = None,
    data_objects: list[DataObjectEvidence] | None = None,
    temporal_checks: dict[str, bool] | None = None,
    cost_checks: dict[str, bool] | None = None,
    sandbox_checks: dict[str, bool] | None = None,
    reproducibility_hashes: list[str] | None = None,
    missing_evidence: list[str] | None = None,
    artifact_sha256: str | None = None,
) -> BacktestEvidence:
    plan = _plan()
    payload = {
        "schema_version": 1,
        "binding": BINDING.model_dump(mode="json"),
        "task_digest": plan.task_digest,
        "step_id": plan.step_id,
        "request_id": plan.request_id,
        "plan_digest": plan.plan_digest,
        "data_snapshot_digest": SHA_A,
        "engine_digest": plan.adapter.engine_digest,
        "policy_digest": canonical_sha256(plan.execution_policy),
        "status": status.value,
        "data_objects": [
            DataObjectEvidence(
                logical_dataset="cta-benchmark-rb-1m",
                object_uri="snapshot://rb-v1/ohlcv.parquet",
                version_id="rb-v1",
                content_sha256=SHA_A,
                schema_sha256=SHA_B,
                rows=500_000,
                start_date=date(2020, 1, 1),
                end_date=date(2020, 12, 31),
            ).model_dump(mode="json")
        ]
        if data_objects is None
        else [item.model_dump(mode="json") for item in data_objects],
        "temporal_checks": temporal_checks
        if temporal_checks is not None
        else {"strict_timestamp": True, "non_overlapping_oos": True, "next_bar_fill": True},
        "cost_checks": cost_checks
        if cost_checks is not None
        else {"commission_nonzero": True, "slippage_nonzero": True},
        "sandbox_checks": sandbox_checks
        if sandbox_checks is not None
        else {"network_disabled": True, "raw_data_read_only": True},
        "reproducibility_hashes": reproducibility_hashes
        if reproducibility_hashes is not None
        else [SHA_A, SHA_A],
        "metrics": (
            (metrics or _metrics()).model_dump(mode="json")
            if metrics is not None or status == EvidenceStatus.PASS
            else None
        ),
        "missing_evidence": missing_evidence or [],
    }
    digest = canonical_sha256(payload)
    return BacktestEvidence(**payload, artifact_sha256=artifact_sha256 or digest)


def _review(evidence: BacktestEvidence, proposal: ReviewerProposal | None = None):
    return review_risk_evidence(
        evidence=evidence,
        plan=_plan(),
        policy=_policy(),
        expected_binding=BINDING,
        reviewer_proposal=proposal,
    )


def test_complete_evidence_produces_canonical_bound_pass() -> None:
    evidence = _evidence(metrics=_metrics())
    artifact = _review(evidence)

    assert artifact.verdict == AgenticRiskGateVerdict.PASS
    assert artifact.binding == BINDING
    assert artifact.plan_digest == _plan().plan_digest
    assert artifact.evidence_digest == evidence.artifact_sha256
    assert artifact.policy_digest == decision_policy_digest(_policy())
    payload = artifact.model_dump(mode="json")
    digest = payload.pop("artifact_sha256")
    assert digest == canonical_sha256(payload)


def _dynamic_task() -> RiskGateTaskArtifact:
    draft = RiskGateTaskDraft(
        binding=BINDING,
        trigger=RiskGateTrigger(
            decision="required",
            confidence=0.9,
            reasons=[
                RiskGateReason(
                    summary="Strategy behavior changed.",
                    evidence_refs=["ev-diff"],
                )
            ],
            risk_domains=["strategy-behavior"],
        ),
        scope=RiskGateScope(
            included=[
                RiskGateScopeTarget(
                    target="strategies/dual_ma.py",
                    changed_files=["strategies/dual_ma.py"],
                    rationale="Changed strategy subject.",
                    evidence_refs=["ev-diff"],
                )
            ],
            coverage=RiskGateCoverage(
                changed_files_total=1,
                changed_files_examined=1,
                complete=True,
            ),
        ),
        process=[
            RiskGateProcessStep(
                step_id="backtest-oos",
                objective="Run the selected out-of-sample risk backtest.",
                method="Use the trusted single-asset adapter.",
                capability_id="single-asset-backtrader-v1",
                evidence_outputs=["backtest-evidence.json"],
                acceptance_criteria=["Every required policy check has evidence."],
                failure_action="block",
            )
        ],
        execution_requests=[
            RiskGateExecutionRequest(
                request_id="run-backtest-oos",
                step_id="backtest-oos",
                capability_id="single-asset-backtrader-v1",
                parameters={"risk_gate_plan": plan_proposal_projection(_plan())},
            )
        ],
        execution_ready=True,
        deliverables=["backtest-evidence.json"],
        evidence=[
            RiskGateEvidence(
                evidence_id="ev-diff",
                kind="git.changed-file-diff",
                locator="git:base...head:strategies/dual_ma.py",
                content_sha256=SHA_A,
                summary="Bounded strategy diff.",
                changed_files=["strategies/dual_ma.py"],
                revision=BINDING.head_sha,
            )
        ],
        subagent=RiskGateSubagentProvenance(
            subagent_id="risk-scout-test",
            model="test-model",
            prompt_sha256=SHA_A,
            tool_calls=2,
        ),
    )
    return RiskGateTaskArtifact.finalize(draft)


def _task_bound_plan_and_evidence() -> tuple[RiskGateTaskArtifact, RiskGatePlan, BacktestEvidence]:
    task = _dynamic_task()
    plan_payload = _plan().model_dump(mode="json")
    plan_payload.pop("plan_digest")
    plan_payload.update(
        {
            "task_digest": task.artifact_sha256,
            "step_id": "backtest-oos",
            "request_id": "run-backtest-oos",
        }
    )
    plan = RiskGatePlan.finalize(RiskGatePlanDraft.model_validate(plan_payload))
    evidence_payload = _evidence(metrics=_metrics()).model_dump(mode="json")
    evidence_payload.pop("artifact_sha256")
    evidence_payload.update(
        {
            "task_digest": task.artifact_sha256,
            "step_id": plan.step_id,
            "request_id": plan.request_id,
            "plan_digest": plan.plan_digest,
        }
    )
    evidence = BacktestEvidence(
        **evidence_payload,
        artifact_sha256=canonical_sha256(evidence_payload),
    )
    return task, plan, evidence


def test_dynamic_task_step_request_and_evidence_are_bound_to_final_verdict() -> None:
    task, plan, evidence = _task_bound_plan_and_evidence()
    artifact = review_risk_evidence(
        task=task,
        evidence=evidence,
        plan=plan,
        policy=_policy(),
        expected_binding=BINDING,
    )
    assert artifact.verdict == AgenticRiskGateVerdict.PASS
    assert artifact.task_digest == task.artifact_sha256
    assert artifact.completed_step_ids == ["backtest-oos"]

    mismatched_payload = evidence.model_dump(mode="json")
    mismatched_payload.pop("artifact_sha256")
    mismatched_payload["request_id"] = "different-request"
    mismatched = BacktestEvidence(
        **mismatched_payload,
        artifact_sha256=canonical_sha256(mismatched_payload),
    )
    blocked = review_risk_evidence(
        task=task,
        evidence=mismatched,
        plan=plan,
        policy=_policy(),
        expected_binding=BINDING,
    )
    assert blocked.verdict == AgenticRiskGateVerdict.BLOCK
    assert any(finding.code == "TASK_STEP_MISMATCH" for finding in blocked.findings)

    changed_plan_payload = plan.model_dump(mode="json")
    changed_plan_payload.pop("plan_digest")
    changed_plan_payload["adapter_parameters"]["position_size"] = 0.5
    changed_plan = RiskGatePlan.finalize(
        RiskGatePlanDraft.model_validate(changed_plan_payload)
    )
    changed_evidence_payload = evidence.model_dump(mode="json")
    changed_evidence_payload.pop("artifact_sha256")
    changed_evidence_payload["plan_digest"] = changed_plan.plan_digest
    changed_evidence = BacktestEvidence(
        **changed_evidence_payload,
        artifact_sha256=canonical_sha256(changed_evidence_payload),
    )
    blocked = review_risk_evidence(
        task=task,
        evidence=changed_evidence,
        plan=changed_plan,
        policy=_policy(),
        expected_binding=BINDING,
    )
    assert blocked.verdict == AgenticRiskGateVerdict.BLOCK
    assert any(finding.code == "TASK_DIGEST_MISMATCH" for finding in blocked.findings)


@pytest.mark.parametrize(
    ("mutation", "missing_prefix", "finding_code"),
    [
        ("provenance", "provenance:", "MISSING_DATA_PROVENANCE"),
        ("pit", "pit:", "MISSING_PIT_EVIDENCE"),
        ("cost", "cost:", "MISSING_COST_EVIDENCE"),
        ("repro", "reproducibility:", "MISSING_REPRODUCIBILITY"),
        ("correlation", "metric:correlation", "MISSING_CORRELATION"),
        ("capacity", "metric:capacity", "MISSING_CAPACITY"),
    ],
)
def test_mandatory_missing_evidence_is_not_evaluable_and_never_human_overridable(
    mutation: str, missing_prefix: str, finding_code: str
) -> None:
    kwargs: dict = {"status": EvidenceStatus.BLOCK, "metrics": _metrics()}
    if mutation == "provenance":
        kwargs["data_objects"] = []
    elif mutation == "pit":
        kwargs["temporal_checks"] = {"non_overlapping_oos": True, "next_bar_fill": True}
    elif mutation == "cost":
        kwargs["cost_checks"] = {"commission_nonzero": True}
    elif mutation == "repro":
        kwargs["reproducibility_hashes"] = []
    elif mutation == "correlation":
        kwargs["metrics"] = _metrics(correlation_with_existing=None)
    elif mutation == "capacity":
        kwargs["metrics"] = _metrics(capacity_estimate_usd=None)

    artifact = _review(_evidence(**kwargs))
    assert artifact.verdict == AgenticRiskGateVerdict.NOT_EVALUABLE
    assert artifact.human_gate_allowed is False
    assert any(item.startswith(missing_prefix) for item in artifact.missing_evidence)
    assert finding_code in {finding.code for finding in artifact.findings}
    assert all(finding.overridable is False for finding in artifact.findings)


@pytest.mark.parametrize(
    "kwargs,code",
    [
        (
            {
                "temporal_checks": {
                    "strict_timestamp": False,
                    "non_overlapping_oos": True,
                    "next_bar_fill": True,
                }
            },
            "PIT_CHECK_FAILED",
        ),
        (
            {"cost_checks": {"commission_nonzero": False, "slippage_nonzero": True}},
            "COST_CHECK_FAILED",
        ),
        ({"reproducibility_hashes": [SHA_A, SHA_B]}, "NON_REPRODUCIBLE"),
    ],
)
def test_failed_pit_cost_or_reproducibility_is_non_overridable_block(
    kwargs: dict, code: str
) -> None:
    artifact = _review(_evidence(status=EvidenceStatus.BLOCK, metrics=_metrics(), **kwargs))
    assert artifact.verdict == AgenticRiskGateVerdict.BLOCK
    assert artifact.human_gate_allowed is False
    assert code in {finding.code for finding in artifact.findings}
    assert all(finding.overridable is False for finding in artifact.findings)


def test_reducer_closes_evidence_model_pass_gaps() -> None:
    no_provenance = _evidence(status=EvidenceStatus.PASS, metrics=_metrics(), data_objects=[])
    artifact = _review(no_provenance)
    assert artifact.verdict == AgenticRiskGateVerdict.NOT_EVALUABLE
    assert "MISSING_DATA_PROVENANCE" in {finding.code for finding in artifact.findings}

    fake_repro = _evidence(
        status=EvidenceStatus.PASS,
        metrics=_metrics(),
        reproducibility_hashes=["x", "x"],
    )
    artifact = _review(fake_repro)
    assert artifact.verdict == AgenticRiskGateVerdict.BLOCK
    assert "NON_REPRODUCIBLE" in {finding.code for finding in artifact.findings}


def test_risk_appetite_threshold_can_enter_human_gate_only_when_evidence_is_complete() -> None:
    artifact = _review(_evidence(metrics=_metrics(max_drawdown=0.20)))
    assert artifact.verdict == AgenticRiskGateVerdict.NEEDS_HUMAN
    assert artifact.human_gate_allowed is True
    assert {finding.code for finding in artifact.findings} == {"MAX_DRAWDOWN"}
    assert all(finding.overridable for finding in artifact.findings)


def test_model_proposal_contains_findings_only_and_cannot_override_missing_capacity() -> None:
    with pytest.raises(ValidationError):
        ReviewerProposal.model_validate(
            {
                "verdict": "pass",
                "human_gate_allowed": True,
                "findings": [{"code": "REGIME_SENSITIVITY", "message": "unstable"}],
            }
        )
    proposal = ReviewerProposal.model_validate(
        {
            "findings": [
                {
                    "code": "REGIME_SENSITIVITY",
                    "message": "Regime sensitivity merits review.",
                }
            ]
        }
    )
    artifact = _review(
        _evidence(
            status=EvidenceStatus.BLOCK,
            metrics=_metrics(capacity_estimate_usd=None),
        ),
        proposal,
    )
    assert artifact.verdict == AgenticRiskGateVerdict.NOT_EVALUABLE
    assert artifact.human_gate_allowed is False
    assert all(finding.overridable is False for finding in artifact.findings)


def test_policy_not_model_controls_reviewer_finding_disposition() -> None:
    human = ReviewerProposal.model_validate(
        {"findings": [{"code": "REGIME_SENSITIVITY", "message": "Regime sensitivity detected."}]}
    )
    block = ReviewerProposal.model_validate(
        {"findings": [{"code": "UNMODELLED_TAIL", "message": "Tail exposure is unmodelled."}]}
    )
    assert (
        _review(_evidence(metrics=_metrics()), human).verdict
        == AgenticRiskGateVerdict.NEEDS_HUMAN
    )
    blocked = _review(_evidence(metrics=_metrics()), block)
    assert blocked.verdict == AgenticRiskGateVerdict.BLOCK
    assert blocked.human_gate_allowed is False


def test_digest_or_pr_binding_tamper_is_non_overridable_block() -> None:
    tampered = _evidence(metrics=_metrics(), artifact_sha256=SHA_B)
    artifact = _review(tampered)
    assert artifact.verdict == AgenticRiskGateVerdict.BLOCK
    assert "EVIDENCE_DIGEST_MISMATCH" in {finding.code for finding in artifact.findings}

    other_binding = BINDING.model_copy(update={"head_sha": "3" * 40})
    artifact = review_risk_evidence(
        evidence=_evidence(metrics=_metrics()),
        plan=_plan(),
        policy=_policy(),
        expected_binding=other_binding,
    )
    assert artifact.verdict == AgenticRiskGateVerdict.BLOCK
    assert artifact.binding == other_binding
    assert all(finding.overridable is False for finding in artifact.findings)


def test_reviewer_context_has_aggregate_evidence_only() -> None:
    context = build_reviewer_context(
        evidence=_evidence(metrics=_metrics()), plan=_plan(), policy=_policy()
    )
    encoded = json.dumps(context, sort_keys=True)
    assert "data_objects" not in context
    assert "object_uri" not in encoded
    assert "data_requests" not in context
    assert "raw_data_payload" not in encoded
    assert "github" not in encoded.lower()
    assert "shell" not in encoded.lower()
    assert set(context["proposal_schema"]["properties"]) == {"findings"}


def test_wrapped_executor_evidence_loader_accepts_only_the_evidence_contract(
    tmp_path: Path,
) -> None:
    evidence = _evidence(metrics=_metrics())
    path = tmp_path / "backtest-evidence.json"
    path.write_text(json.dumps({"evidence": evidence.model_dump(mode="json"), "raw": "ignored"}))
    assert load_evidence(path) == evidence


def test_policy_requires_versioned_correlation_and_capacity_contract() -> None:
    payload = _policy().model_dump(mode="json")
    payload["required_metrics"].remove("capacity_estimate_usd")
    with pytest.raises(ValidationError, match="correlation and capacity"):
        RiskReviewPolicy.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["non_overridable_blocks"] = []
    with pytest.raises(ValidationError, match="cannot weaken"):
        RiskReviewPolicy.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["reviewer_finding_rules"].append(
        {"code": "MISSING_CORRELATION", "disposition": "needs_human"}
    )
    with pytest.raises(ValidationError, match="cannot redefine mandatory"):
        RiskReviewPolicy.model_validate(payload)


def test_unbounded_executor_missing_text_is_safely_reduced() -> None:
    artifact = _review(
        _evidence(
            status=EvidenceStatus.BLOCK,
            metrics=_metrics(),
            missing_evidence=["missing " + ("x" * 5000)],
        )
    )
    assert artifact.verdict == AgenticRiskGateVerdict.NOT_EVALUABLE
    assert artifact.human_gate_allowed is False
    assert all(len(finding.message) <= 2048 for finding in artifact.findings)
    assert all(len(item) <= len("evidence:") + 512 for item in artifact.missing_evidence)


def test_policy_loader_selects_plan_policy_from_versioned_registry(tmp_path: Path) -> None:
    policy = _policy().model_dump(mode="json")
    policy.pop("policy_id")
    schema_version = policy.pop("schema_version")
    catalog = {
        "schema_version": schema_version,
        "risk_policies": {"quant-risk-v1": policy},
        "adapters": {"not-part-of-decision-policy": {"entrypoint": "ignored"}},
    }
    path = tmp_path / "risk_gate_catalog.yaml"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    loaded = load_policy(path, policy_id=_plan().risk_policy_id)
    assert loaded == _policy()
    assert decision_policy_digest(loaded) == decision_policy_digest(_policy())
    with pytest.raises(ValueError, match="absent from registry"):
        load_policy(path, policy_id="unknown-risk-v9")


def test_versioned_policy_not_workflow_controls_threshold_verdict() -> None:
    payload = _policy().model_dump(mode="json")
    payload["thresholds"][0].update(
        {"limit": 0.05, "disposition": FindingDisposition.BLOCK.value}
    )
    stricter = RiskReviewPolicy.model_validate(payload)
    artifact = review_risk_evidence(
        evidence=_evidence(metrics=_metrics()),
        plan=_plan(),
        policy=stricter,
        expected_binding=BINDING,
    )
    assert artifact.verdict == AgenticRiskGateVerdict.BLOCK
    assert artifact.policy_digest == decision_policy_digest(stricter)
    assert artifact.policy_digest != decision_policy_digest(_policy())


def test_not_applicable_plan_returns_canonical_artifact_without_fake_evidence() -> None:
    plan = RiskGatePlan.finalize(
        RiskGatePlanDraft(
            binding=BINDING,
            applicability=RiskApplicability.NOT_APPLICABLE,
            risk_policy_id="quant-risk-v1",
            rationale="Documentation-only change.",
            planner_model="test-risk-scope-subagent",
            prompt_digest=SHA_A,
        )
    )

    artifact = review_plan_without_execution(
        plan=plan,
        policy=_policy(),
        expected_binding=BINDING,
    )

    assert artifact.verdict == AgenticRiskGateVerdict.NOT_APPLICABLE
    assert artifact.findings == []
    assert artifact.missing_evidence == []
    assert artifact.evidence_digest == canonical_sha256(
        {"applicability": "not_applicable", "plan_digest": plan.plan_digest}
    )


def test_not_evaluable_plan_returns_missing_contract_without_human_override() -> None:
    plan = RiskGatePlan.finalize(
        RiskGatePlanDraft(
            binding=BINDING,
            applicability=RiskApplicability.NOT_EVALUABLE,
            risk_policy_id="quant-risk-v1",
            rationale="Strategy source has no approved execution contract.",
            missing_requirements=["BacktestManifest", "immutable data binding"],
            planner_model="test-risk-scope-subagent",
            prompt_digest=SHA_A,
        )
    )

    artifact = review_plan_without_execution(
        plan=plan,
        policy=_policy(),
        expected_binding=BINDING,
    )

    assert artifact.verdict == AgenticRiskGateVerdict.NOT_EVALUABLE
    assert artifact.human_gate_allowed is False
    assert artifact.missing_evidence == ["BacktestManifest", "immutable data binding"]
    assert {item.code for item in artifact.findings} == {"MISSING_BACKTEST_CONTRACT"}


def test_evaluable_plan_without_executor_evidence_is_error_not_pass() -> None:
    artifact = review_plan_without_execution(
        plan=_plan(),
        policy=_policy(),
        expected_binding=BINDING,
    )

    assert artifact.verdict == AgenticRiskGateVerdict.ERROR
    assert artifact.human_gate_allowed is False
    assert artifact.missing_evidence
