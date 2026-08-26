#!/usr/bin/env python3
"""Reduce trusted backtest evidence into a canonical RiskGateArtifact.

The optional model contribution is deliberately narrow: callers may supply a
JSON proposal containing findings only.  This module does not call a model,
run a shell command, read raw market data, or write to GitHub.  A versioned
trusted policy and deterministic evidence checks are the only verdict authority.

Digest semantics are intentionally explicit:

* ``BacktestEvidence.policy_digest`` binds the plan's ``ExecutionPolicy``.
* ``RiskGateArtifact.policy_digest`` binds the selected risk-decision policy.
* ``RiskGateArtifact.evidence_digest`` is the recomputed canonical evidence hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.risk_gate_artifact import (
    AgenticRiskGateVerdict,
    BacktestEvidence,
    BacktestRiskMetrics,
    EvidenceStatus,
    PRBinding,
    RiskApplicability,
    RiskFinding,
    RiskGateArtifact,
    RiskGatePlan,
    RiskGatePlanProposal,
)
from schemas.risk_gate_task import RiskGateTaskArtifact, RiskGateTriggerDecision


MAX_INPUT_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHECK_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
CORE_REQUIRED_METRICS = {"correlation_with_existing", "capacity_estimate_usd"}
CORE_NON_OVERRIDABLE_BLOCKS = {
    "missing_cost_model",
    "missing_provenance",
    "missing_required_metric",
    "non_reproducible",
    "temporal_leakage",
}
MANDATORY_CODES = {
    "COST_CHECK_FAILED",
    "EVIDENCE_BLOCKED",
    "EVIDENCE_DIGEST_MISMATCH",
    "EVIDENCE_ERROR",
    "ENGINE_DIGEST_MISMATCH",
    "EXECUTION_POLICY_MISMATCH",
    "MISSING_CAPACITY",
    "MISSING_CORRELATION",
    "MISSING_COST_EVIDENCE",
    "MISSING_DATA_PROVENANCE",
    "MISSING_PIT_EVIDENCE",
    "MISSING_REQUIRED_METRIC",
    "MISSING_REPRODUCIBILITY",
    "NON_REPRODUCIBLE",
    "PIT_CHECK_FAILED",
    "PLAN_BINDING_MISMATCH",
    "PLAN_DIGEST_MISMATCH",
    "POLICY_ID_MISMATCH",
    "PR_BINDING_MISMATCH",
    "SANDBOX_CHECK_FAILED",
    "TASK_BINDING_MISMATCH",
    "TASK_DIGEST_MISMATCH",
    "TASK_STEP_MISMATCH",
}


class ThresholdComparator(StrEnum):
    MAX = "max"
    MIN = "min"
    ABS_MAX = "abs_max"


class FindingDisposition(StrEnum):
    INFO = "info"
    WARNING = "warning"
    NEEDS_HUMAN = "needs_human"
    BLOCK = "block"


class ThresholdRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9_]{2,64}$")
    metric: str = Field(min_length=1, max_length=128)
    comparator: ThresholdComparator
    limit: float
    disposition: FindingDisposition
    message: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def _finite_limit(self) -> Self:
        if not math.isfinite(self.limit):
            raise ValueError("threshold limit must be finite")
        return self


class ReviewerFindingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9_]{2,64}$")
    disposition: FindingDisposition = FindingDisposition.WARNING


class RiskReviewPolicy(BaseModel):
    """Versioned, digest-bound policy consumed by the trusted reducer."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    required_temporal_checks: list[str] = Field(min_length=1, max_length=128)
    required_cost_checks: list[str] = Field(min_length=1, max_length=128)
    required_sandbox_checks: list[str] = Field(min_length=1, max_length=128)
    required_metrics: list[str] = Field(min_length=1, max_length=128)
    non_overridable_blocks: list[str] = Field(
        default_factory=lambda: sorted(CORE_NON_OVERRIDABLE_BLOCKS), max_length=128
    )
    thresholds: list[ThresholdRule] = Field(default_factory=list, max_length=128)
    reviewer_finding_rules: list[ReviewerFindingRule] = Field(
        default_factory=list, max_length=128
    )

    @model_validator(mode="after")
    def _policy_contract(self) -> Self:
        metric_names = set(BacktestRiskMetrics.model_fields)
        groups = (
            self.required_temporal_checks,
            self.required_cost_checks,
            self.required_sandbox_checks,
        )
        for checks in groups:
            invalid_name = any(not CHECK_NAME_RE.fullmatch(item) for item in checks)
            if len(checks) != len(set(checks)) or invalid_name:
                raise ValueError("required check names must be unique canonical identifiers")
        if len(self.required_metrics) != len(set(self.required_metrics)):
            raise ValueError("required metrics must be unique")
        if not CORE_REQUIRED_METRICS.issubset(self.required_metrics):
            raise ValueError("policy must require correlation and capacity")
        if unknown := set(self.required_metrics) - metric_names:
            raise ValueError(f"unknown required metrics: {sorted(unknown)}")
        if not CORE_NON_OVERRIDABLE_BLOCKS.issubset(self.non_overridable_blocks):
            raise ValueError("policy cannot weaken non-overridable evidence failures")
        if len(self.non_overridable_blocks) != len(set(self.non_overridable_blocks)):
            raise ValueError("non-overridable block names must be unique")

        codes = [rule.code for rule in self.thresholds]
        codes.extend(rule.code for rule in self.reviewer_finding_rules)
        if len(codes) != len(set(codes)):
            raise ValueError("policy finding codes must be unique")
        if MANDATORY_CODES.intersection(codes):
            raise ValueError("policy cannot redefine mandatory evidence findings")
        for rule in self.thresholds:
            if rule.metric not in self.required_metrics:
                raise ValueError(f"threshold metric must be required: {rule.metric}")
        return self


class ReviewerFindingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9_]{2,64}$")
    message: str = Field(min_length=1, max_length=2048)


class ReviewerProposal(BaseModel):
    """Untrusted reviewer output: no verdict, severity, tools, or side effects."""

    model_config = ConfigDict(extra="forbid")

    findings: list[ReviewerFindingProposal] = Field(default_factory=list, max_length=100)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_evidence_digest(evidence: BacktestEvidence) -> str:
    payload = evidence.model_dump(mode="json")
    payload.pop("artifact_sha256", None)
    return canonical_sha256(payload)


def decision_policy_digest(policy: RiskReviewPolicy) -> str:
    return canonical_sha256(policy)


def _execution_policy_digest(plan: RiskGatePlan) -> str | None:
    if plan.execution_policy is None:
        return None
    return canonical_sha256(plan.execution_policy)


def build_reviewer_context(
    *, evidence: BacktestEvidence, plan: RiskGatePlan, policy: RiskReviewPolicy
) -> dict[str, Any]:
    """Return aggregate-only context safe to send to an optional reviewer."""

    return {
        "schema_version": 1,
        "binding": plan.binding.model_dump(mode="json"),
        "plan_digest": plan.plan_digest,
        "evidence_digest": canonical_evidence_digest(evidence),
        "decision_policy_digest": decision_policy_digest(policy),
        "evidence_status": evidence.status.value,
        "checks": {
            "temporal": dict(sorted(evidence.temporal_checks.items())),
            "cost": dict(sorted(evidence.cost_checks.items())),
            "sandbox": dict(sorted(evidence.sandbox_checks.items())),
        },
        "metrics": evidence.metrics.model_dump(mode="json") if evidence.metrics else None,
        "missing_evidence": sorted(set(evidence.missing_evidence)),
        "thresholds": [rule.model_dump(mode="json") for rule in policy.thresholds],
        "proposal_schema": ReviewerProposal.model_json_schema(),
    }


class _Reduction:
    def __init__(self) -> None:
        self.findings: list[tuple[RiskFinding, FindingDisposition]] = []
        self.missing: set[str] = set()
        self.hard_block = False
        self.error = False
        self.human = False

    def add(
        self,
        *,
        code: str,
        message: str,
        disposition: FindingDisposition,
        mandatory: bool = False,
    ) -> None:
        if mandatory and disposition == FindingDisposition.NEEDS_HUMAN:
            raise ValueError("mandatory evidence findings cannot be human-overridden")
        message = " ".join(str(message).split())[:2048]
        if not message:
            message = "Risk review finding has no printable explanation."
        severity = {
            FindingDisposition.INFO: "info",
            FindingDisposition.WARNING: "warning",
            FindingDisposition.NEEDS_HUMAN: "blocker",
            FindingDisposition.BLOCK: "blocker",
        }[disposition]
        self.findings.append(
            (
                RiskFinding(
                    code=code,
                    severity=severity,
                    message=message,
                    overridable=disposition == FindingDisposition.NEEDS_HUMAN,
                ),
                disposition,
            )
        )
        if disposition == FindingDisposition.BLOCK:
            self.hard_block = True
        elif disposition == FindingDisposition.NEEDS_HUMAN:
            self.human = True

    def missing_item(self, item: str, *, code: str, message: str) -> None:
        normalized = " ".join(str(item).split())[:512]
        self.missing.add(normalized or "unspecified")
        self.add(
            code=code,
            message=message,
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )


def _same_binding(left: PRBinding, right: PRBinding) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def plan_proposal_projection(plan: RiskGatePlan) -> dict[str, Any]:
    return RiskGatePlanProposal(
        applicability=plan.applicability,
        subjects=plan.subjects,
        data_requests=plan.data_requests,
        adapter_id=plan.adapter.adapter_id if plan.adapter is not None else None,
        adapter_parameters=plan.adapter_parameters,
        window=plan.window,
        execution_policy=plan.execution_policy,
        benchmark=plan.benchmark,
        risk_policy_id=plan.risk_policy_id,
        rationale=plan.rationale,
        missing_requirements=plan.missing_requirements,
    ).model_dump(mode="json")


def _check_dynamic_task_binding(
    reduction: _Reduction,
    *,
    task: RiskGateTaskArtifact | None,
    plan: RiskGatePlan,
    evidence: BacktestEvidence | None,
    expected_binding: PRBinding,
) -> list[str]:
    if task is None:
        if plan.task_digest is not None:
            reduction.add(
                code="TASK_BINDING_MISMATCH",
                message="A task-bound plan was reviewed without its RiskGateTaskArtifact.",
                disposition=FindingDisposition.BLOCK,
                mandatory=True,
            )
        return []
    if not _same_binding(task.binding, expected_binding):
        reduction.add(
            code="TASK_BINDING_MISMATCH",
            message="RiskGateTaskArtifact does not match the trusted PR head binding.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    if plan.task_digest != task.artifact_sha256:
        reduction.add(
            code="TASK_DIGEST_MISMATCH",
            message="RiskGatePlan is not bound to the canonical dynamic task Artifact.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    required_steps = {step.step_id for step in task.process if step.required}
    steps_by_id = {step.step_id: step for step in task.process}
    requests_by_id = {
        request.request_id: request for request in task.execution_requests
    }
    completed: list[str] = []
    if evidence is not None:
        if (
            task.trigger.decision != RiskGateTriggerDecision.REQUIRED
            or not task.execution_ready
            or not task.scope.coverage.complete
            or task.scope.unknowns
            or task.missing_requirements
        ):
            reduction.add(
                code="TASK_STEP_MISMATCH",
                message="Dynamic task did not authorize automatic evidence execution.",
                disposition=FindingDisposition.BLOCK,
                mandatory=True,
            )
        if evidence.task_digest != task.artifact_sha256:
            reduction.add(
                code="TASK_DIGEST_MISMATCH",
                message="BacktestEvidence is not bound to the canonical dynamic task Artifact.",
                disposition=FindingDisposition.BLOCK,
                mandatory=True,
            )
        bound_request = requests_by_id.get(plan.request_id or "")
        bound_step = steps_by_id.get(plan.step_id or "")
        if (
            plan.step_id is None
            or plan.request_id is None
            or bound_request is None
            or bound_step is None
            or bound_request.step_id != plan.step_id
            or bound_request.capability_id != bound_step.capability_id
            or plan.adapter is None
            or plan.adapter.adapter_id != bound_request.capability_id
            or evidence.step_id != plan.step_id
            or evidence.request_id != plan.request_id
            or plan.step_id not in required_steps
        ):
            reduction.add(
                code="TASK_STEP_MISMATCH",
                message="Evidence step/request does not match a required dynamic task step.",
                disposition=FindingDisposition.BLOCK,
                mandatory=True,
            )
        else:
            requested_plan = bound_request.parameters.get("risk_gate_plan")
            if not isinstance(requested_plan, dict) or (
                RiskGatePlanProposal.model_validate(requested_plan).model_dump(mode="json")
                != plan_proposal_projection(plan)
            ):
                reduction.add(
                    code="TASK_DIGEST_MISMATCH",
                    message="RiskGatePlan content differs from the task execution request.",
                    disposition=FindingDisposition.BLOCK,
                    mandatory=True,
                )
            else:
                completed.append(plan.step_id)
    if task.trigger.decision == RiskGateTriggerDecision.REQUIRED:
        if evidence is not None and set(completed) != required_steps:
            reduction.add(
                code="TASK_STEP_MISMATCH",
                message="Not every required dynamic Risk Gate step has bound evidence.",
                disposition=FindingDisposition.BLOCK,
                mandatory=True,
            )
    elif evidence is not None:
        reduction.add(
            code="TASK_STEP_MISMATCH",
            message=(
                "A non-required or indeterminate task unexpectedly produced execution evidence."
            ),
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    return completed


def _check_bindings_and_digests(
    reduction: _Reduction,
    *,
    evidence: BacktestEvidence,
    plan: RiskGatePlan,
    policy: RiskReviewPolicy,
    expected_binding: PRBinding,
) -> str:
    evidence_digest = canonical_evidence_digest(evidence)
    if not _same_binding(plan.binding, expected_binding):
        reduction.add(
            code="PLAN_BINDING_MISMATCH",
            message="RiskGatePlan does not match the trusted repository/PR/head binding.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    if not _same_binding(evidence.binding, expected_binding):
        reduction.add(
            code="PR_BINDING_MISMATCH",
            message="BacktestEvidence does not match the trusted repository/PR/head binding.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    if evidence.plan_digest != plan.plan_digest:
        reduction.add(
            code="PLAN_DIGEST_MISMATCH",
            message="BacktestEvidence is not bound to the selected canonical plan.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    if evidence.artifact_sha256 != evidence_digest:
        reduction.add(
            code="EVIDENCE_DIGEST_MISMATCH",
            message="BacktestEvidence canonical digest does not match artifact_sha256.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    if policy.policy_id != plan.risk_policy_id:
        reduction.add(
            code="POLICY_ID_MISMATCH",
            message="Selected decision policy does not match RiskGatePlan.risk_policy_id.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    execution_digest = _execution_policy_digest(plan)
    if execution_digest is None:
        reduction.missing_item(
            "provenance:execution_policy",
            code="MISSING_DATA_PROVENANCE",
            message="The plan has no execution policy to bind the evidence.",
        )
    elif evidence.policy_digest != execution_digest:
        reduction.add(
            code="EXECUTION_POLICY_MISMATCH",
            message="BacktestEvidence execution-policy digest does not match the plan.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    if plan.adapter is None:
        reduction.missing_item(
            "provenance:adapter",
            code="MISSING_DATA_PROVENANCE",
            message="The selected plan has no trusted adapter provenance.",
        )
    elif evidence.engine_digest != plan.adapter.engine_digest:
        reduction.add(
            code="ENGINE_DIGEST_MISMATCH",
            message="BacktestEvidence engine digest does not match the trusted plan adapter.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    return evidence_digest


def _check_provenance(
    reduction: _Reduction, evidence: BacktestEvidence, plan: RiskGatePlan
) -> None:
    if plan.applicability != RiskApplicability.EVALUABLE:
        reduction.missing_item(
            "plan:evaluable",
            code="MISSING_DATA_PROVENANCE",
            message="Evidence review requires an evaluable canonical RiskGatePlan.",
        )
    if not evidence.data_objects:
        reduction.missing_item(
            "provenance:data_objects",
            code="MISSING_DATA_PROVENANCE",
            message="No immutable data-object provenance was supplied.",
        )
        return
    objects_by_dataset: dict[str, list[Any]] = {}
    for item in evidence.data_objects:
        objects_by_dataset.setdefault(item.logical_dataset, []).append(item)
        if item.rows == 0:
            reduction.missing_item(
                f"provenance:rows:{item.logical_dataset}",
                code="MISSING_DATA_PROVENANCE",
                message=f"Data object {item.logical_dataset} contains no rows.",
            )
    for request in plan.data_requests:
        objects = objects_by_dataset.get(request.logical_dataset, [])
        if not objects:
            reduction.missing_item(
                f"provenance:dataset:{request.logical_dataset}",
                code="MISSING_DATA_PROVENANCE",
                message=f"No immutable object proves dataset {request.logical_dataset}.",
            )
            continue
        if not any(
            item.start_date is not None
            and item.end_date is not None
            and item.start_date <= request.start_date
            and item.end_date >= request.end_date
            for item in objects
        ):
            reduction.missing_item(
                f"pit:date_coverage:{request.logical_dataset}",
                code="MISSING_PIT_EVIDENCE",
                message=(
                    f"Dataset {request.logical_dataset} does not prove requested date coverage."
                ),
            )


def _check_named_checks(
    reduction: _Reduction,
    *,
    category: str,
    checks: dict[str, bool],
    required: list[str],
    missing_code: str,
    failed_code: str,
) -> None:
    for name in required:
        if name not in checks:
            reduction.missing_item(
                f"{category}:{name}",
                code=missing_code,
                message=f"Required {category} check is absent: {name}.",
            )
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        reduction.add(
            code=failed_code,
            message=f"Failed {category} checks: {', '.join(failed)}.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )


def _check_reproducibility(reduction: _Reduction, evidence: BacktestEvidence) -> None:
    hashes = evidence.reproducibility_hashes
    if len(hashes) < 2:
        reduction.missing_item(
            "reproducibility:two_runs",
            code="MISSING_REPRODUCIBILITY",
            message="At least two deterministic backtest hashes are required.",
        )
        return
    if any(not SHA256_RE.fullmatch(item) for item in hashes) or len(set(hashes)) != 1:
        reduction.add(
            code="NON_REPRODUCIBLE",
            message="Backtest reruns are invalid or do not have one identical canonical hash.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )


def _metric_values(metrics: BacktestRiskMetrics | None) -> dict[str, float | None]:
    if metrics is None:
        return {}
    return metrics.model_dump(mode="python")


def _check_metrics(
    reduction: _Reduction, evidence: BacktestEvidence, policy: RiskReviewPolicy
) -> dict[str, float | None]:
    metrics = _metric_values(evidence.metrics)
    for name in policy.required_metrics:
        value = metrics.get(name)
        if value is None:
            code = {
                "correlation_with_existing": "MISSING_CORRELATION",
                "capacity_estimate_usd": "MISSING_CAPACITY",
            }.get(name, "MISSING_REQUIRED_METRIC")
            reduction.missing_item(
                f"metric:{name}",
                code=code,
                message=f"Required risk metric is absent: {name}.",
            )
        elif not math.isfinite(float(value)):
            reduction.add(
                code="MISSING_REQUIRED_METRIC",
                message=f"Required risk metric is not finite: {name}.",
                disposition=FindingDisposition.BLOCK,
                mandatory=True,
            )
    return metrics


def _threshold_breached(rule: ThresholdRule, value: float) -> bool:
    if rule.comparator == ThresholdComparator.MAX:
        return value > rule.limit
    if rule.comparator == ThresholdComparator.MIN:
        return value < rule.limit
    return abs(value) > rule.limit


def _apply_policy_thresholds(
    reduction: _Reduction, *, metrics: dict[str, float | None], policy: RiskReviewPolicy
) -> None:
    for rule in policy.thresholds:
        value = metrics.get(rule.metric)
        if value is None or not math.isfinite(float(value)):
            continue
        if _threshold_breached(rule, float(value)):
            reduction.add(
                code=rule.code,
                message=rule.message,
                disposition=rule.disposition,
            )


def _apply_reviewer_proposal(
    reduction: _Reduction,
    *,
    proposal: ReviewerProposal | None,
    policy: RiskReviewPolicy,
) -> None:
    if proposal is None:
        return
    rules = {rule.code: rule for rule in policy.reviewer_finding_rules}
    for proposed in proposal.findings:
        rule = rules.get(proposed.code)
        if rule is None:
            reduction.add(
                code="REVIEW_UNMAPPED",
                message=f"Unmapped reviewer finding {proposed.code}: {proposed.message}",
                disposition=FindingDisposition.WARNING,
            )
            continue
        reduction.add(
            code=proposed.code,
            message=proposed.message,
            disposition=rule.disposition,
        )


def _finalize_findings(
    reduction: _Reduction, verdict: AgenticRiskGateVerdict
) -> list[RiskFinding]:
    unique: dict[tuple[str, str], RiskFinding] = {}
    for finding, _disposition in reduction.findings:
        unique[(finding.code, finding.message)] = finding
    findings = [unique[key] for key in sorted(unique)]
    if verdict == AgenticRiskGateVerdict.NEEDS_HUMAN:
        findings = [finding.model_copy(update={"overridable": True}) for finding in findings]
    elif verdict in {
        AgenticRiskGateVerdict.BLOCK,
        AgenticRiskGateVerdict.ERROR,
        AgenticRiskGateVerdict.NOT_EVALUABLE,
    }:
        findings = [finding.model_copy(update={"overridable": False}) for finding in findings]
    return findings


def review_risk_evidence(
    *,
    evidence: BacktestEvidence,
    plan: RiskGatePlan,
    policy: RiskReviewPolicy,
    expected_binding: PRBinding,
    task: RiskGateTaskArtifact | None = None,
    reviewer_proposal: ReviewerProposal | None = None,
) -> RiskGateArtifact:
    """Apply trusted invariants and policy; model output never sets the verdict."""

    reduction = _Reduction()
    completed_steps = _check_dynamic_task_binding(
        reduction,
        task=task,
        plan=plan,
        evidence=evidence,
        expected_binding=expected_binding,
    )
    evidence_digest = _check_bindings_and_digests(
        reduction,
        evidence=evidence,
        plan=plan,
        policy=policy,
        expected_binding=expected_binding,
    )
    _check_provenance(reduction, evidence, plan)
    _check_named_checks(
        reduction,
        category="pit",
        checks=evidence.temporal_checks,
        required=policy.required_temporal_checks,
        missing_code="MISSING_PIT_EVIDENCE",
        failed_code="PIT_CHECK_FAILED",
    )
    _check_named_checks(
        reduction,
        category="cost",
        checks=evidence.cost_checks,
        required=policy.required_cost_checks,
        missing_code="MISSING_COST_EVIDENCE",
        failed_code="COST_CHECK_FAILED",
    )
    _check_named_checks(
        reduction,
        category="sandbox",
        checks=evidence.sandbox_checks,
        required=policy.required_sandbox_checks,
        missing_code="MISSING_DATA_PROVENANCE",
        failed_code="SANDBOX_CHECK_FAILED",
    )
    _check_reproducibility(reduction, evidence)
    metrics = _check_metrics(reduction, evidence, policy)
    _apply_policy_thresholds(reduction, metrics=metrics, policy=policy)
    _apply_reviewer_proposal(reduction, proposal=reviewer_proposal, policy=policy)

    reported_missing = sorted(
        {
            " ".join(str(item).split())[:512]
            for item in evidence.missing_evidence
            if str(item).strip()
        }
    )[:100]
    for item in reported_missing:
        reduction.missing.add(f"evidence:{item}")
    if reported_missing:
        reduction.add(
            code="MISSING_DATA_PROVENANCE",
            message="Executor reported missing evidence: " + "; ".join(reported_missing),
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    if evidence.status == EvidenceStatus.ERROR:
        reduction.error = True
        reduction.add(
            code="EVIDENCE_ERROR",
            message="The trusted backtest executor reported an error.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )
    elif (
        evidence.status == EvidenceStatus.BLOCK
        and not reduction.missing
        and not reduction.hard_block
    ):
        reduction.add(
            code="EVIDENCE_BLOCKED",
            message="The trusted backtest executor blocked this evidence.",
            disposition=FindingDisposition.BLOCK,
            mandatory=True,
        )

    if reduction.missing:
        verdict = AgenticRiskGateVerdict.NOT_EVALUABLE
    elif reduction.error:
        verdict = AgenticRiskGateVerdict.ERROR
    elif reduction.hard_block:
        verdict = AgenticRiskGateVerdict.BLOCK
    elif reduction.human:
        verdict = AgenticRiskGateVerdict.NEEDS_HUMAN
    else:
        verdict = AgenticRiskGateVerdict.PASS

    findings = _finalize_findings(reduction, verdict)
    payload = {
        "schema_version": 1,
        "binding": expected_binding.model_dump(mode="json"),
        "task_digest": task.artifact_sha256 if task is not None else plan.task_digest,
        "plan_digest": plan.plan_digest,
        "evidence_digest": evidence_digest,
        "policy_digest": decision_policy_digest(policy),
        "verdict": verdict.value,
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "missing_evidence": sorted(reduction.missing),
        "completed_step_ids": completed_steps,
        "human_gate_allowed": verdict == AgenticRiskGateVerdict.NEEDS_HUMAN,
    }
    return RiskGateArtifact(**payload, artifact_sha256=canonical_sha256(payload))


def review_plan_without_execution(
    *,
    plan: RiskGatePlan,
    policy: RiskReviewPolicy,
    expected_binding: PRBinding,
    task: RiskGateTaskArtifact | None = None,
) -> RiskGateArtifact:
    """Finalize a canonical plan that correctly requires no executor evidence.

    Only ``not_applicable`` and ``not_evaluable`` normally use this path. An
    evaluable plan without evidence is an infrastructure error, never a pass.
    """

    if not _same_binding(plan.binding, expected_binding):
        raise ValueError("RiskGatePlan does not match the trusted repository/PR/head binding")
    if policy.policy_id != plan.risk_policy_id:
        raise ValueError("selected decision policy does not match RiskGatePlan.risk_policy_id")
    if task is not None:
        if not _same_binding(task.binding, expected_binding):
            raise ValueError("RiskGateTaskArtifact does not match the trusted PR head binding")
        if plan.task_digest != task.artifact_sha256:
            raise ValueError("RiskGatePlan does not bind the canonical dynamic task")

    no_execution = {
        "applicability": plan.applicability.value,
        "plan_digest": plan.plan_digest,
    }
    missing: list[str] = []
    findings: list[RiskFinding] = []
    if plan.applicability == RiskApplicability.NOT_APPLICABLE:
        if task is not None and task.trigger.decision != RiskGateTriggerDecision.NOT_REQUIRED:
            verdict = AgenticRiskGateVerdict.ERROR
            missing = ["dynamic task did not authorize a not_applicable verdict"]
            findings = [
                RiskFinding(
                    code="TASK_STEP_MISMATCH",
                    severity="blocker",
                    message=missing[0],
                    overridable=False,
                )
            ]
        else:
            verdict = AgenticRiskGateVerdict.NOT_APPLICABLE
    elif plan.applicability == RiskApplicability.NOT_EVALUABLE:
        verdict = AgenticRiskGateVerdict.NOT_EVALUABLE
        missing = sorted(set(plan.missing_requirements))
        findings = [
            RiskFinding(
                code="MISSING_BACKTEST_CONTRACT",
                severity="blocker",
                message=item,
                overridable=False,
            )
            for item in missing
        ]
    else:
        verdict = AgenticRiskGateVerdict.ERROR
        missing = ["trusted executor produced no BacktestEvidence for an evaluable plan"]
        findings = [
            RiskFinding(
                code="EVIDENCE_ERROR",
                severity="blocker",
                message=missing[0],
                overridable=False,
            )
        ]

    payload = {
        "schema_version": 1,
        "binding": expected_binding.model_dump(mode="json"),
        "task_digest": task.artifact_sha256 if task is not None else plan.task_digest,
        "plan_digest": plan.plan_digest,
        "evidence_digest": canonical_sha256(no_execution),
        "policy_digest": decision_policy_digest(policy),
        "verdict": verdict.value,
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "missing_evidence": missing,
        "completed_step_ids": [],
        "human_gate_allowed": False,
    }
    return RiskGateArtifact(**payload, artifact_sha256=canonical_sha256(payload))


def _load_structured(path: Path) -> Any:
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"input size is outside the 1 MiB contract: {path}")
    return yaml.safe_load(raw.decode("utf-8"))


def load_evidence(path: Path) -> BacktestEvidence:
    payload = _load_structured(path)
    if isinstance(payload, dict) and "evidence" in payload:
        payload = payload["evidence"]
    return BacktestEvidence.model_validate(payload)


def load_plan(path: Path) -> RiskGatePlan:
    return RiskGatePlan.model_validate(_load_structured(path))


def load_task(path: Path) -> RiskGateTaskArtifact:
    return RiskGateTaskArtifact.model_validate(_load_structured(path))


def load_policy(path: Path, *, policy_id: str | None = None) -> RiskReviewPolicy:
    """Load a flat policy or select one policy from a versioned catalog registry."""

    payload = _load_structured(path)
    if not isinstance(payload, dict):
        raise ValueError("risk policy document must be an object")
    if "risk_policies" in payload:
        if not policy_id:
            raise ValueError("policy_id is required when loading a risk_policies registry")
        registry = payload.get("risk_policies")
        selected = registry.get(policy_id) if isinstance(registry, dict) else None
        if not isinstance(selected, dict):
            raise ValueError(f"risk policy is absent from registry: {policy_id}")
        payload = {
            **selected,
            "schema_version": payload.get("schema_version", 1),
            "policy_id": policy_id,
        }
    policy = RiskReviewPolicy.model_validate(payload)
    if policy_id and policy.policy_id != policy_id:
        raise ValueError("flat policy does not match requested policy_id")
    return policy


def load_reviewer_proposal(path: Path | None) -> ReviewerProposal | None:
    if path is None:
        return None
    return ReviewerProposal.model_validate(_load_structured(path))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reduce BacktestEvidence into RiskGateArtifact.")
    parser.add_argument("--evidence")
    parser.add_argument("--task", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--reviewer-proposal")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    binding = PRBinding(
        repository=args.repository,
        pr_number=args.pr_number,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
    )
    plan = load_plan(Path(args.plan).resolve())
    task = load_task(Path(args.task).resolve())
    policy = load_policy(Path(args.policy).resolve(), policy_id=plan.risk_policy_id)
    if args.evidence:
        artifact = review_risk_evidence(
            evidence=load_evidence(Path(args.evidence).resolve()),
            plan=plan,
            policy=policy,
            expected_binding=binding,
            task=task,
            reviewer_proposal=load_reviewer_proposal(
                Path(args.reviewer_proposal).resolve() if args.reviewer_proposal else None
            ),
        )
    else:
        if args.reviewer_proposal:
            raise ValueError("reviewer proposal requires BacktestEvidence")
        artifact = review_plan_without_execution(
            plan=plan,
            policy=policy,
            expected_binding=binding,
            task=task,
        )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
