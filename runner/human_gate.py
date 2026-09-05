"""HumanGate helpers for merge and permission only."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from schemas.human_gate import HumanGateInterruptPayload

_GATE_MESSAGE = "⏸️ 等待人工审批"

# ---------------------------------------------------------------------------
# Decision vocabulary normalization  (Day 7 OpenCode human-gate integration)
# ---------------------------------------------------------------------------
# OpenCode 对外的 approve/reject，对内映射为 ReAct 路径的 proceed/abort。

_EXTERNAL_TO_INTERNAL: dict[str, str] = {
    "approve": "proceed",
    "reject": "abort",
    "proceed": "proceed",
    "abort": "abort",
}


def normalize_external_decision(decision: str) -> Literal["approve", "reject"]:
    """将任意变体映射为 OpenCode 可见的 approve/reject。

    approve/proceed → "approve" ; reject/abort → "reject" ; 其他 → "reject"（fail-closed）。
    """
    normalized = _EXTERNAL_TO_INTERNAL.get(
        str(decision).strip().lower() if decision else ""
    )
    if normalized in ("proceed",):
        return "approve"
    return "reject"


def to_react_resume_payload(decision: str) -> dict[str, str]:
    """将 OpenCode 决策转为 ReAct request_human_review 用的 resume payload。

    approve → {"decision": "proceed"}  ;  reject → {"decision": "abort"}.
    """
    internal = _EXTERNAL_TO_INTERNAL.get(
        str(decision).strip().lower() if decision else ""
    )
    return {"decision": internal or "abort"}


def _gate_payload_for_opencode(
    *,
    thread_id: str,
    gate_id: str,
    message: str,
    reasons: list[str],
    kind: str,
    resource: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 OpenCode 可直接展示的 gate 字段（从 interrupt payload 提取并标准化）。"""
    return {
        "kind": kind,
        "gate_id": gate_id,
        "thread_id": thread_id,
        "message": message,
        "reasons": reasons,
        "resource": resource,
        "evidence": evidence or {},
        "decision_schema": {
            "allowed": ["approve", "reject"],
            "default": "reject",
        },
    }


def make_gate_id(thread_id: str) -> str:
    """生成带 UUID 后缀的稳定唯一 gate_id。"""
    safe_tid = thread_id.replace(":", "_").replace("/", "_")
    return f"hg_{safe_tid}_{uuid.uuid4().hex[:12]}"


def build_interrupt_payload(
    *,
    gate_id: str,
    kind: Literal["merge", "permission"],
    resource: str | None = None,
    actor: str | None = None,
    evidence: dict[str, Any] | None = None,
    reasons: list[str],
    decision: str | None = None,
    message: str = _GATE_MESSAGE,
) -> dict[str, Any]:
    """构造 LangGraph interrupt 用的结构化 payload。"""
    payload = HumanGateInterruptPayload(
        gate_id=gate_id,
        kind=kind,
        resource=resource,
        actor=actor,
        evidence=evidence or {},
        message=message,
        reasons=reasons,
        decision=decision,
    )
    return payload.model_dump(mode="json")


def parse_resume_decision(resume_payload: Any) -> str | None:
    """从 LangGraph resume payload 解析 decision 字符串。"""
    if isinstance(resume_payload, dict):
        return resume_payload.get("decision")
    return None


# ---------------------------------------------------------------------------
# OpenCode interrupt 提取 / 格式化  (Day 7)
# ---------------------------------------------------------------------------


def extract_interrupt_payload(state: dict[str, Any]) -> dict[str, Any] | None:
    """从 LangGraph 返回的 state 中提取 pending interrupt payload。

    LangGraph interrupt 在 state["__interrupt__"] 列表中，每个元素有 .value。
    返回 None 表示没有 pending interrupt。
    """
    interrupts = state.get("__interrupt__")
    if not interrupts:
        return None
    try:
        interrupt = interrupts[0]
        value = getattr(interrupt, "value", interrupt)
        if isinstance(value, dict):
            return value
    except (IndexError, TypeError, AttributeError):
        pass
    return None


def format_waiting_for_human(
    *,
    thread_id: str,
    interrupt_payload: dict[str, Any],
) -> dict[str, Any]:
    """构造 MCP run_agent "waiting_for_human" 结果。

    从 interrupt payload 提取 gate_id、message、reasons 等字段，
    调用 _gate_payload_for_opencode 组装 OpenCode 可展示的 gate。
    """
    payload = HumanGateInterruptPayload.model_validate(interrupt_payload)
    gate_id = payload.gate_id
    message = payload.message
    reasons = payload.reasons
    kind = payload.kind

    gate = _gate_payload_for_opencode(
        thread_id=thread_id,
        gate_id=gate_id,
        message=message,
        reasons=list(reasons) if isinstance(reasons, list) else [str(reasons)],
        kind=kind,
        resource=payload.resource,
        evidence=payload.evidence,
    )

    return {
        "status": "waiting_for_human",
        "thread_id": thread_id,
        "gate": gate,
    }
