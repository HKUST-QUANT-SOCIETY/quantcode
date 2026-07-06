"""QuantCode Pattern 5 — HumanGate (Human-in-the-Loop Gate)."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

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
    """风控流程中需要人工审批的关卡。"""

    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    status: HumanGateStatus
    decision: HumanGateDecision | None = None


class HumanGateInterruptPayload(BaseModel):
    """LangGraph interrupt/resume 时传递的结构化 HumanGate payload（单一真相源）。"""

    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    risk_profile: dict[str, Any]
    reasons: list[str]
    decision: str | None = None
