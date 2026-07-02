"""
QuantCode Pattern 5 — HumanGate (Human-in-the-Loop Gate).

风控流程中需要人工审批的关卡，用于记录触发条件、风险阈值、超时策略、通知方式和最终人工决策。
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .compose_task import SESSION_ID_PATTERN, TASK_ID_PATTERN


class HumanGateStatus(StrEnum):
    """人工审批关卡状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


class HumanGateTrigger(StrEnum):
    """触发人工审批的原因。"""

    MAX_DRAWDOWN_EXCEEDED = "max_drawdown_exceeded"
    POSITION_LIMIT_EXCEEDED = "position_limit_exceeded"
    CORRELATION_EXCEEDED = "correlation_exceeded"
    VAR_EXCEEDED = "var_exceeded"
    MISSING_RISK_PROFILE = "missing_risk_profile"
    RISK_GATE_UNCERTAIN = "risk_gate_uncertain"
    MANUAL_REQUEST = "manual_request"
    WORKFLOW_FAILURE = "workflow_failure"


class NotifyChannel(StrEnum):
    """通知人工 reviewer 的方式。"""

    GITHUB_PR_COMMENT = "github_pr_comment"
    GITHUB_ISSUE = "github_issue"
    SLACK = "slack"
    EMAIL = "email"
    OPENCODE = "opencode"
    MANUAL = "manual"


class HumanGateDecisionAction(StrEnum):
    """人工审批结果动作。"""

    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"


class RiskMetrics(BaseModel):
    """风控指标阈值或观测值。"""

    model_config = ConfigDict(extra="forbid")

    max_drawdown: float | None = Field(default=None, ge=0, le=1)
    position_limit: float | None = Field(default=None, ge=0, le=1)
    correlation_with_existing: float | None = Field(default=None, ge=-1, le=1)
    tail_risk_var_99: float | None = None


class HumanGateDecision(BaseModel):
    """人工审批结果；pending 状态下 HumanGate.decision 可以为 null。"""

    model_config = ConfigDict(extra="forbid")

    action: HumanGateDecisionAction
    decided_by: str
    decided_at: datetime
    reason: str
    conditions: list[str] | None = Field(
        default=None,
        description="有条件通过时的附加限制",
    )

    @field_serializer("decided_at", when_used="json")
    def _serialize_decided_at(self, dt: datetime) -> int:
        return int(dt.timestamp())


class HumanGate(BaseModel):
    """
    风控流程中需要人工审批的关卡。

    pending 状态下 decision 可以为 None；approved / rejected / escalated
    状态下必须有 decision。
    """

    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(description="HumanGate 唯一 ID，建议格式 hg_<task_id>_<timestamp>")
    task_id: str = Field(pattern=TASK_ID_PATTERN, description="关联的 ComposeTask task_id")
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)
    pr_url: str | None = Field(
        default=None,
        description="触发本次风控审批的 GitHub PR 链接 (URI)",
    )
    head_sha: str | None = Field(
        default=None,
        description="触发审批时 PR 对应的 commit SHA，用于 dedupe",
    )
    status: HumanGateStatus
    trigger: HumanGateTrigger
    trigger_reason: str | None = Field(
        default=None,
        description="自然语言说明，解释为什么需要人工审批",
    )
    risk_thresholds: RiskMetrics = Field(description="触发 HumanGate 的风控阈值")
    observed_values: RiskMetrics | None = Field(
        default=None,
        description="实际检测到的风控指标值，通常来自 RiskProfile",
    )
    timeout_minutes: int = Field(ge=1, description="等待人工审批的最长时间，超过后进入 timed_out")
    created_at: datetime = Field(description="HumanGate 创建时间")
    expires_at: datetime | None = Field(default=None, description="HumanGate 超时时间")
    notify_channels: list[NotifyChannel] = Field(
        min_length=1,
        description="通知人工 reviewer 的方式",
    )
    required_approvers: list[str] = Field(
        min_length=1,
        description="需要参与审批的人或角色",
    )
    decision: HumanGateDecision | None = Field(
        default=None,
        description="人工审批结果；pending 状态下可以为 null",
    )
    dedupe_key: str | None = Field(
        default=None,
        description="用于避免 GitHub PR 重复评论的稳定 key，建议包含 pr_url 和 head_sha",
    )
    analyst_notes: str | None = Field(
        default=None,
        description="risk-gate 或 reviewer 生成的补充说明",
    )

    @field_serializer("created_at", "expires_at", when_used="json")
    def _serialize_ts(self, dt: datetime | None) -> int | None:
        return int(dt.timestamp()) if dt else None

    @field_validator("notify_channels", mode="after")
    @classmethod
    def _unique_notify_channels(cls, v: list[NotifyChannel]) -> list[NotifyChannel]:
        if len(v) != len(set(v)):
            raise ValueError("notify_channels must be unique")
        return v

    @field_validator("required_approvers", mode="after")
    @classmethod
    def _unique_required_approvers(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("required_approvers must be unique")
        return v

    @model_validator(mode="after")
    def _decision_consistency(self) -> "HumanGate":
        needs_decision = {
            HumanGateStatus.APPROVED,
            HumanGateStatus.REJECTED,
            HumanGateStatus.ESCALATED,
        }
        if self.status in needs_decision and self.decision is None:
            raise ValueError(f"status={self.status.value} requires decision")
        return self
