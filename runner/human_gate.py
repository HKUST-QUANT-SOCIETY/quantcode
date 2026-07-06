"""HumanGate runner — 阈值判断、gate_id 生成、interrupt payload 构造。"""
from __future__ import annotations

import uuid
from typing import Any

from schemas.human_gate import (
    HumanGate,
    HumanGateInterruptPayload,
    HumanGateStatus,
)
from schemas.risk_profile import RiskProfile, RiskThresholds

_GATE_MESSAGE = "⏸️ 等待人工审批"
_RESOLVED_STATUSES = {
    HumanGateStatus.APPROVED,
    HumanGateStatus.REJECTED,
}


def should_interrupt(
    profile: RiskProfile,
    thresholds: RiskThresholds,
    gate: HumanGate | None = None,
) -> bool:
    """检查是否需要触发 HumanGate（暂停 workflow 等待人工审批）。"""
    if gate is not None and gate.status in _RESOLVED_STATUSES:
        return False
    return bool(profile.breached_thresholds(thresholds))


def gate_check(profile: RiskProfile, thresholds: RiskThresholds) -> dict[str, Any]:
    """返回 requires_human 与 reasons（与 tools.risk.check_gate 对齐）。"""
    reasons = profile.breached_thresholds(thresholds)
    return {
        "requires_human": bool(reasons),
        "reasons": reasons,
    }


def make_gate_id(thread_id: str) -> str:
    """生成带 UUID 后缀的稳定唯一 gate_id。"""
    safe_tid = thread_id.replace(":", "_").replace("/", "_")
    return f"hg_{safe_tid}_{uuid.uuid4().hex[:12]}"


def build_interrupt_payload(
    *,
    gate_id: str,
    risk_profile: dict[str, Any],
    reasons: list[str],
    decision: str | None = None,
    message: str = _GATE_MESSAGE,
) -> dict[str, Any]:
    """构造 LangGraph interrupt 用的结构化 payload。"""
    payload = HumanGateInterruptPayload(
        gate_id=gate_id,
        message=message,
        risk_profile=risk_profile,
        reasons=reasons,
        decision=decision,
    )
    return payload.model_dump(mode="json")


def parse_resume_decision(resume_payload: Any) -> str | None:
    """从 LangGraph resume payload 解析 decision 字符串。"""
    if isinstance(resume_payload, dict):
        return resume_payload.get("decision")
    return None
