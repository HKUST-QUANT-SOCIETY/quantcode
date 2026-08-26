"""Dynamic Risk Gate task artifact produced by a bounded Risk Scout subagent.

The business scope and checking process are intentionally open-ended.  The
trusted contract fixes only provenance, evidence references, dependency
integrity, and fail-closed semantics.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ._compat import Self, StrEnum
from .risk_gate_artifact import PRBinding, SHA256_PATTERN


IDENTIFIER_PATTERN = r"^[a-z0-9][a-z0-9_.:-]{0,127}$"
REFERENCE_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$"


class RiskGateTriggerDecision(StrEnum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    INDETERMINATE = "indeterminate"


class RiskGateFailureAction(StrEnum):
    BLOCK = "block"
    HUMAN_REVIEW = "human_review"
    REVISE_PLAN = "revise_plan"


class RiskGateEvidence(BaseModel):
    """One trusted, redacted observation made through a read-only tool."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=REFERENCE_PATTERN)
    kind: str = Field(pattern=IDENTIFIER_PATTERN)
    locator: str = Field(min_length=1, max_length=1024)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    summary: str = Field(min_length=1, max_length=2048)
    changed_files: list[str] = Field(default_factory=list, max_length=500)
    revision: str | None = Field(default=None, max_length=64)
    redacted: bool = True


class RiskGateReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2048)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)


class RiskGateTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: RiskGateTriggerDecision
    confidence: float = Field(ge=0, le=1)
    reasons: list[RiskGateReason] = Field(min_length=1, max_length=100)
    # Domains are deliberately strings rather than an enum.  A new business
    # risk must not require a code release before the scout can describe it.
    risk_domains: list[str] = Field(default_factory=list, max_length=100)


class RiskGateScopeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, max_length=1024)
    changed_files: list[str] = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2048)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)


class RiskGateCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_files_total: int = Field(ge=0, le=500)
    changed_files_examined: int = Field(ge=0, le=500)
    complete: bool

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> Self:
        if self.changed_files_examined > self.changed_files_total:
            raise ValueError("examined changed-file count exceeds total")
        if self.complete != (self.changed_files_examined == self.changed_files_total):
            raise ValueError("coverage.complete does not match changed-file counts")
        return self


class RiskGateScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    included: list[RiskGateScopeTarget] = Field(default_factory=list, max_length=200)
    excluded: list[RiskGateScopeTarget] = Field(default_factory=list, max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    unknowns: list[str] = Field(default_factory=list, max_length=100)
    coverage: RiskGateCoverage


class RiskGateProcessStep(BaseModel):
    """A subagent-designed check; capability_id is resolved by trusted code."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(pattern=REFERENCE_PATTERN)
    objective: str = Field(min_length=1, max_length=2048)
    method: str = Field(min_length=1, max_length=4096)
    capability_id: str = Field(pattern=IDENTIFIER_PATTERN)
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    required: bool = True
    inputs: list[str] = Field(default_factory=list, max_length=100)
    evidence_outputs: list[str] = Field(min_length=1, max_length=100)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)
    failure_action: RiskGateFailureAction


class RiskGateExecutionRequest(BaseModel):
    """Untrusted capability request; never an arbitrary command or entrypoint."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=REFERENCE_PATTERN)
    step_id: str = Field(pattern=REFERENCE_PATTERN)
    capability_id: str = Field(pattern=IDENTIFIER_PATTERN)
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=128)

    @model_validator(mode="after")
    def _parameters_are_bounded(self) -> Self:
        encoded = json.dumps(
            self.parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > 64 * 1024:
            raise ValueError("risk execution request parameters exceed 64 KiB")
        return self


class RiskGateSubagentProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subagent_id: str = Field(pattern=IDENTIFIER_PATTERN)
    parent_task_id: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    role: str = Field(default="risk-scout", pattern=IDENTIFIER_PATTERN)
    model: str = Field(min_length=1, max_length=128)
    prompt_sha256: str = Field(pattern=SHA256_PATTERN)
    # Zero is reserved for a trusted fail-closed Artifact created when the
    # provider/subagent cannot start. It can never be execution-ready.
    tool_calls: int = Field(ge=0, le=32)
    protocol: str = Field(default="bounded-readonly-v1", pattern=IDENTIFIER_PATTERN)


class RiskGateTaskProposal(BaseModel):
    """Model-authored portion before trusted evidence and PR binding are added."""

    model_config = ConfigDict(extra="forbid")

    decision: RiskGateTriggerDecision
    confidence: float = Field(ge=0, le=1)
    reasons: list[RiskGateReason] = Field(min_length=1, max_length=100)
    risk_domains: list[str] = Field(default_factory=list, max_length=100)
    included: list[RiskGateScopeTarget] = Field(default_factory=list, max_length=200)
    excluded: list[RiskGateScopeTarget] = Field(default_factory=list, max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    unknowns: list[str] = Field(default_factory=list, max_length=100)
    examined_changed_files: list[str] = Field(default_factory=list, max_length=500)
    process: list[RiskGateProcessStep] = Field(default_factory=list, max_length=100)
    execution_requests: list[RiskGateExecutionRequest] = Field(default_factory=list, max_length=100)
    deliverables: list[str] = Field(default_factory=list, max_length=100)
    missing_requirements: list[str] = Field(default_factory=list, max_length=100)


class RiskGateTaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    artifact_type: str = Field(
        default="dynamic-risk-gate-task", pattern=r"^dynamic-risk-gate-task$"
    )
    binding: PRBinding
    trigger: RiskGateTrigger
    scope: RiskGateScope
    process: list[RiskGateProcessStep] = Field(default_factory=list, max_length=100)
    execution_requests: list[RiskGateExecutionRequest] = Field(default_factory=list, max_length=100)
    execution_ready: bool = False
    deliverables: list[str] = Field(default_factory=list, max_length=100)
    missing_requirements: list[str] = Field(default_factory=list, max_length=100)
    evidence: list[RiskGateEvidence] = Field(min_length=1, max_length=500)
    subagent: RiskGateSubagentProvenance

    @model_validator(mode="after")
    def _contract_is_self_consistent(self) -> Self:
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("risk task evidence ids must be unique")
        known_evidence = set(evidence_ids)
        references: list[str] = []
        references.extend(ref for reason in self.trigger.reasons for ref in reason.evidence_refs)
        for target in [*self.scope.included, *self.scope.excluded]:
            references.extend(target.evidence_refs)
        if unknown := set(references) - known_evidence:
            raise ValueError(f"risk task contains dangling evidence references: {sorted(unknown)}")

        steps = {step.step_id: step for step in self.process}
        if len(steps) != len(self.process):
            raise ValueError("risk task process step ids must be unique")
        for step in self.process:
            if step.step_id in step.depends_on:
                raise ValueError("risk task process step cannot depend on itself")
            if unknown := set(step.depends_on) - set(steps):
                raise ValueError(f"risk task has unknown step dependencies: {sorted(unknown)}")
        self._assert_acyclic(steps)

        request_ids = [request.request_id for request in self.execution_requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("risk execution request ids must be unique")
        requests_by_step: dict[str, list[RiskGateExecutionRequest]] = {}
        for request in self.execution_requests:
            step = steps.get(request.step_id)
            if step is None:
                raise ValueError("risk execution request references an unknown process step")
            if request.capability_id != step.capability_id:
                raise ValueError(
                    "risk execution request capability does not match its process step"
                )
            requests_by_step.setdefault(request.step_id, []).append(request)

        decision = self.trigger.decision
        if decision == RiskGateTriggerDecision.NOT_REQUIRED:
            if (
                self.process
                or self.execution_requests
                or self.scope.included
                or self.scope.unknowns
                or self.missing_requirements
                or not self.scope.coverage.complete
                or self.execution_ready
            ):
                raise ValueError("not_required requires complete evidence and no execution plan")
        elif decision == RiskGateTriggerDecision.INDETERMINATE:
            if not self.scope.unknowns and not self.missing_requirements:
                raise ValueError("indeterminate task must explain missing context")
            if self.execution_ready:
                raise ValueError("indeterminate task cannot be execution-ready")
        else:
            if not self.scope.included or not self.process:
                raise ValueError("required Risk Gate needs included scope and a process")
            if self.execution_ready:
                if (
                    self.scope.unknowns
                    or self.missing_requirements
                    or not self.scope.coverage.complete
                ):
                    raise ValueError("execution-ready task cannot have unknown or missing context")
                missing_requests = [
                    step.step_id
                    for step in self.process
                    if step.required and step.step_id not in requests_by_step
                ]
                if missing_requests:
                    raise ValueError(
                        f"execution-ready task lacks capability requests: {missing_requests}"
                    )
        return self

    @staticmethod
    def _assert_acyclic(steps: dict[str, RiskGateProcessStep]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("risk task process dependencies contain a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in steps[step_id].depends_on:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in steps:
            visit(step_id)


class RiskGateTaskArtifact(RiskGateTaskDraft):
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)

    @staticmethod
    def _digest_payload(data: dict[str, Any]) -> str:
        payload = dict(data)
        payload.pop("artifact_sha256", None)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def finalize(cls, draft: RiskGateTaskDraft) -> "RiskGateTaskArtifact":
        data = draft.model_dump(mode="json")
        return cls(**data, artifact_sha256=cls._digest_payload(data))

    @model_validator(mode="after")
    def _digest_matches(self) -> Self:
        if self.artifact_sha256 != self._digest_payload(self.model_dump(mode="json")):
            raise ValueError("artifact_sha256 does not match canonical Risk Gate task")
        return self
