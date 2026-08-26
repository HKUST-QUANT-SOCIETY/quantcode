"""Contracts for agent-planned, evidence-backed Risk Gate execution."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._compat import Self, StrEnum


SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"


class RiskApplicability(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    EVALUABLE = "evaluable"
    NOT_EVALUABLE = "not_evaluable"


class RiskSubjectKind(StrEnum):
    FACTOR = "factor"
    MODEL = "model"
    STRATEGY = "strategy"
    OPTIONS = "options"
    PORTFOLIO = "portfolio"


class AgenticRiskGateVerdict(StrEnum):
    PASS = "pass"
    NEEDS_HUMAN = "needs_human"
    BLOCK = "block"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"
    NOT_EVALUABLE = "not_evaluable"


class EvidenceStatus(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    ERROR = "error"


class PRBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    pr_number: int = Field(ge=1)
    base_sha: str = Field(pattern=GIT_SHA_PATTERN)
    head_sha: str = Field(pattern=GIT_SHA_PATTERN)


class RiskSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RiskSubjectKind
    identifier: str = Field(min_length=1, max_length=256)
    changed_files: list[str] = Field(min_length=1, max_length=500)
    model_spec_path: str | None = Field(default=None, max_length=512)
    backtest_manifest_path: str | None = Field(default=None, max_length=512)


class DataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_dataset: str = Field(min_length=1, max_length=256)
    fields: list[str] = Field(min_length=1, max_length=128)
    start_date: date
    end_date: date
    universe: str | None = Field(default=None, max_length=128)
    symbols: list[str] = Field(default_factory=list, max_length=5000)
    purpose: str = Field(min_length=1, max_length=1024)
    require_immutable_snapshot: bool = True

    @model_validator(mode="after")
    def _date_order(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("data request start_date must be <= end_date")
        return self


class BacktestWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train_start: date | None = None
    train_end: date | None = None
    validation_start: date | None = None
    validation_end: date | None = None
    oos_start: date
    oos_end: date

    @model_validator(mode="after")
    def _ordered_non_overlapping_windows(self) -> Self:
        if (self.train_start is None) != (self.train_end is None):
            raise ValueError("train_start and train_end must be supplied together")
        if (self.validation_start is None) != (self.validation_end is None):
            raise ValueError("validation_start and validation_end must be supplied together")
        if self.train_start and self.train_start > self.train_end:  # type: ignore[operator]
            raise ValueError("train window is reversed")
        if (
            self.validation_start
            and self.validation_start > self.validation_end  # type: ignore[operator]
        ):
            raise ValueError("validation window is reversed")
        if self.oos_start > self.oos_end:
            raise ValueError("OOS window is reversed")
        preceding_end = self.validation_end or self.train_end
        if preceding_end is not None and preceding_end >= self.oos_start:
            raise ValueError("OOS window must start after training/validation")
        if self.train_end and self.validation_start and self.train_end >= self.validation_start:
            raise ValueError("validation window must start after training")
        return self


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1, max_length=128)
    observation_time: str = Field(min_length=1, max_length=256)
    signal_time: str = Field(min_length=1, max_length=256)
    fill_time: str = Field(min_length=1, max_length=256)
    lag_bars: int = Field(ge=1, le=10000)
    commission_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    stamp_duty_bps: float = Field(ge=0)
    enforce_suspension: bool = True
    enforce_price_limits: bool = True
    enforce_t_plus_one: bool = True


class BacktestAdapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    entrypoint: str = Field(min_length=1, max_length=512)
    code_blob_sha256: str = Field(pattern=SHA256_PATTERN)
    engine_id: str = Field(min_length=1, max_length=128)
    engine_digest: str = Field(pattern=SHA256_PATTERN)


class RiskGatePlanProposal(BaseModel):
    """Untrusted planner output before trusted PR/catalog bindings are injected."""

    model_config = ConfigDict(extra="forbid")

    applicability: RiskApplicability
    subjects: list[RiskSubject] = Field(default_factory=list, max_length=100)
    data_requests: list[DataRequest] = Field(default_factory=list, max_length=100)
    adapter_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    adapter_parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    window: BacktestWindow | None = None
    execution_policy: ExecutionPolicy | None = None
    benchmark: str | None = Field(default=None, max_length=128)
    risk_policy_id: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=4096)
    missing_requirements: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _proposal_contract(self) -> Self:
        if self.applicability == RiskApplicability.EVALUABLE:
            if (
                not self.subjects
                or not self.data_requests
                or not self.adapter_id
                or self.window is None
            ):
                raise ValueError(
                    "evaluable proposal requires subjects, data, adapter_id, and window"
                )
            if (
                self.execution_policy is None
                or not self.adapter_parameters
                or self.missing_requirements
            ):
                raise ValueError("evaluable proposal requires policy and no missing requirements")
        elif self.applicability == RiskApplicability.NOT_APPLICABLE:
            if self.subjects or self.data_requests or self.adapter_id or self.adapter_parameters:
                raise ValueError("not_applicable proposal must not request execution")
        elif not self.missing_requirements:
            raise ValueError("not_evaluable proposal must explain missing requirements")
        return self


class RiskGatePlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    binding: PRBinding
    task_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    step_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    request_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    applicability: RiskApplicability
    subjects: list[RiskSubject] = Field(default_factory=list, max_length=100)
    data_requests: list[DataRequest] = Field(default_factory=list, max_length=100)
    adapter: BacktestAdapter | None = None
    adapter_parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    window: BacktestWindow | None = None
    execution_policy: ExecutionPolicy | None = None
    benchmark: str | None = Field(default=None, max_length=128)
    risk_policy_id: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=4096)
    missing_requirements: list[str] = Field(default_factory=list, max_length=100)
    planner_model: str = Field(min_length=1, max_length=128)
    prompt_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _applicability_contract(self) -> Self:
        if (self.step_id is None) != (self.request_id is None):
            raise ValueError("Risk Gate plan step_id and request_id must be supplied together")
        if self.task_digest is None and (self.step_id is not None or self.request_id is not None):
            raise ValueError("Risk Gate plan step/request binding requires task_digest")
        if self.applicability == RiskApplicability.EVALUABLE:
            if (
                not self.subjects
                or not self.data_requests
                or self.adapter is None
                or self.window is None
            ):
                raise ValueError("evaluable plan requires subjects, data, adapter, and window")
            if self.execution_policy is None or not self.adapter_parameters:
                raise ValueError("evaluable plan requires an execution policy")
            if self.missing_requirements:
                raise ValueError("evaluable plan cannot have missing requirements")
            if self.task_digest is not None and (self.step_id is None or self.request_id is None):
                raise ValueError("dynamic evaluable plan requires task step/request binding")
        elif self.applicability == RiskApplicability.NOT_APPLICABLE:
            if self.subjects or self.data_requests or self.adapter is not None:
                raise ValueError("not_applicable plan must not request execution")
        elif not self.missing_requirements:
            raise ValueError("not_evaluable plan must explain missing requirements")
        return self


class RiskGatePlan(RiskGatePlanDraft):
    plan_digest: str = Field(pattern=SHA256_PATTERN)

    @staticmethod
    def _digest_payload(data: dict[str, Any]) -> str:
        payload = dict(data)
        payload.pop("plan_digest", None)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def finalize(cls, draft: RiskGatePlanDraft) -> "RiskGatePlan":
        data = draft.model_dump(mode="json")
        return cls(**data, plan_digest=cls._digest_payload(data))

    @model_validator(mode="after")
    def _digest_matches(self) -> Self:
        if self.plan_digest != self._digest_payload(self.model_dump(mode="json")):
            raise ValueError("plan_digest does not match canonical plan")
        return self


class DataObjectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_dataset: str
    object_uri: str
    version_id: str | None = None
    etag: str | None = None
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    schema_sha256: str = Field(pattern=SHA256_PATTERN)
    rows: int = Field(ge=0)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _immutable_identity(self) -> Self:
        if not self.version_id and not self.content_sha256:
            raise ValueError("data object requires version_id or content hash")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("data object date range is reversed")
        return self


class BacktestRiskMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_return: float
    annual_return: float | None = None
    sharpe: float | None = None
    volatility: float | None = Field(default=None, ge=0)
    max_drawdown: float = Field(ge=0, le=1)
    tail_risk_var_99: float | None = Field(default=None, ge=0)
    turnover: float | None = Field(default=None, ge=0)
    trading_cost: float | None = Field(default=None, ge=0)
    position_limit: float | None = Field(default=None, ge=0)
    correlation_with_existing: float | None = Field(default=None, ge=-1, le=1)
    capacity_estimate_usd: float | None = Field(default=None, ge=0)


class BacktestEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    binding: PRBinding
    task_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    step_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    request_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    plan_digest: str = Field(pattern=SHA256_PATTERN)
    data_snapshot_digest: str = Field(pattern=SHA256_PATTERN)
    engine_digest: str = Field(pattern=SHA256_PATTERN)
    policy_digest: str = Field(pattern=SHA256_PATTERN)
    status: EvidenceStatus
    data_objects: list[DataObjectEvidence] = Field(default_factory=list)
    temporal_checks: dict[str, bool] = Field(default_factory=dict)
    cost_checks: dict[str, bool] = Field(default_factory=dict)
    sandbox_checks: dict[str, bool] = Field(default_factory=dict)
    reproducibility_hashes: list[str] = Field(default_factory=list)
    metrics: BacktestRiskMetrics | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _pass_requires_complete_evidence(self) -> Self:
        if (self.step_id is None) != (self.request_id is None):
            raise ValueError("evidence step_id and request_id must be supplied together")
        if self.task_digest is None and (self.step_id is not None or self.request_id is not None):
            raise ValueError("evidence step/request binding requires task_digest")
        checks = [
            *self.temporal_checks.values(),
            *self.cost_checks.values(),
            *self.sandbox_checks.values(),
        ]
        if self.status == EvidenceStatus.PASS:
            if self.metrics is None or self.missing_evidence or not checks or not all(checks):
                raise ValueError("passing evidence requires metrics and all checks")
            required_metrics = (
                self.metrics.sharpe,
                self.metrics.volatility,
                self.metrics.tail_risk_var_99,
                self.metrics.turnover,
                self.metrics.trading_cost,
                self.metrics.position_limit,
                self.metrics.correlation_with_existing,
                self.metrics.capacity_estimate_usd,
            )
            if any(value is None for value in required_metrics):
                raise ValueError("passing evidence cannot omit required risk metrics")
            if len(self.reproducibility_hashes) < 2 or len(set(self.reproducibility_hashes)) != 1:
                raise ValueError("passing evidence requires two identical reproducibility hashes")
        return self


class RiskFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9_]{2,64}$")
    severity: str = Field(pattern=r"^(info|warning|blocker)$")
    message: str = Field(min_length=1, max_length=2048)
    overridable: bool = False


class RiskGateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    binding: PRBinding
    task_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    plan_digest: str = Field(pattern=SHA256_PATTERN)
    evidence_digest: str = Field(pattern=SHA256_PATTERN)
    policy_digest: str = Field(pattern=SHA256_PATTERN)
    verdict: AgenticRiskGateVerdict
    findings: list[RiskFinding] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    completed_step_ids: list[str] = Field(default_factory=list, max_length=100)
    human_gate_allowed: bool = False
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _verdict_semantics(self) -> Self:
        blockers = [finding for finding in self.findings if finding.severity == "blocker"]
        if self.verdict == AgenticRiskGateVerdict.PASS:
            if blockers or self.missing_evidence or self.human_gate_allowed:
                raise ValueError("pass cannot contain blockers, missing evidence, or HumanGate")
        if self.verdict == AgenticRiskGateVerdict.NEEDS_HUMAN:
            if not self.human_gate_allowed or not self.findings:
                raise ValueError("needs_human requires explicit overridable findings")
            if any(not finding.overridable for finding in self.findings):
                raise ValueError("non-overridable findings cannot enter HumanGate")
        if self.verdict == AgenticRiskGateVerdict.NOT_APPLICABLE:
            if (
                self.findings
                or self.missing_evidence
                or self.completed_step_ids
                or self.human_gate_allowed
            ):
                raise ValueError(
                    "not_applicable cannot contain findings, missing evidence, "
                    "completed steps, or HumanGate"
                )
        if self.verdict in {
            AgenticRiskGateVerdict.BLOCK,
            AgenticRiskGateVerdict.ERROR,
            AgenticRiskGateVerdict.NOT_EVALUABLE,
        }:
            if self.human_gate_allowed:
                raise ValueError("blocked/error/not_evaluable artifacts cannot be human-overridden")
        if self.verdict == AgenticRiskGateVerdict.NOT_EVALUABLE and not self.missing_evidence:
            raise ValueError("not_evaluable must list missing evidence")
        return self


class HumanGateEvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding: PRBinding
    task_digest: str = Field(pattern=SHA256_PATTERN)
    plan_digest: str = Field(pattern=SHA256_PATTERN)
    evidence_digest: str = Field(pattern=SHA256_PATTERN)
    policy_digest: str = Field(pattern=SHA256_PATTERN)
    risk_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    decision: str = Field(pattern=r"^(approve|reject)$")
    decided_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2048)
    decided_at: datetime

    @model_validator(mode="after")
    def _decision_timestamp_is_timezone_aware(self) -> Self:
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("HumanGate decision timestamp must be timezone-aware")
        return self
