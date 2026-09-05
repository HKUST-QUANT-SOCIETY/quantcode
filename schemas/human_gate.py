"""QuantCode Pattern 5 — HumanGate (Human-in-the-Loop Gate)."""
from __future__ import annotations

from enum import StrEnum
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class HumanGateStatus(StrEnum):
    """人工审批关卡状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class HumanGateDecisionAction(StrEnum):
    """人工审批结果动作。"""

    APPROVE = "approve"
    REJECT = "reject"


class HumanGateDecision(BaseModel):
    """人工审批结果。"""

    model_config = ConfigDict(extra="forbid")

    action: HumanGateDecisionAction
    decided_by: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=2048)


class HumanGate(BaseModel):
    """Shared-write or restricted-access approval record."""

    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    status: HumanGateStatus
    kind: Literal["merge", "permission"]
    resource: str | None = None
    actor: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    decision: HumanGateDecision | None = None


class HumanGateInterruptPayload(BaseModel):
    """LangGraph interrupt/resume 时传递的结构化 HumanGate payload（单一真相源）。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["merge", "permission"]
    resource: str | None = None
    actor: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    gate_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    reasons: list[str]
    decision: str | None = None
