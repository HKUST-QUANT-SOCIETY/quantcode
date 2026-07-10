"""request_human_review tool — 触发 LangGraph interrupt 等待人工审核 — Day 4。

在 human_gate 节点之后，LLM 主动调此 tool 时，通过 ``langgraph.types.interrupt()``
暂停执行，等待人类通过 ``Command(resume=)`` 做出 approve/reject 决策。

Day 4 俞高磊：从 ``random.choice`` stub 替换为真实 interrupt + HumanGate 接口。
"""
from __future__ import annotations

from pydantic import BaseModel

from tools.registry import ToolDef


class HumanReviewArgs(BaseModel):
    """request_human_review 的参数。"""

    reason: str = ""


def request_human_review_execute(args: HumanReviewArgs, ctx: dict) -> dict:
    """通过 LangGraph interrupt 暂停，等待人工审核决策。

    优先使用 ctx 中的 risk_metrics 构造 payload；
    如果 ctx 中没有，构造基本 payload。

    Day 7: 兼容 OpenCode approve/reject 决策—resume payload 里的
    ``approve``/``reject`` 会被映射为内部 ``proceed``/``abort``。
    """
    from runner.human_gate import (
        build_interrupt_payload,
        make_gate_id,
        normalize_external_decision,
        parse_resume_decision,
    )

    thread_id = ctx.get("thread_id", "")
    if not thread_id:
        # Fallback: try to get from state via ctx
        thread_id = ctx.get("source", "mcp")

    risk_metrics = ctx.get("risk_metrics") or {}
    reasons = [args.reason] if args.reason else []

    gate_id = make_gate_id(thread_id)
    payload = build_interrupt_payload(
        gate_id=gate_id,
        risk_profile=risk_metrics,
        reasons=reasons,
        message=f"⏸️ HumanGate: {args.reason}" if args.reason else "⏸️ 等待人工审批",
    )

    # ★ 真暂停：LangGraph 在此处暂停，等待外部 Command(resume=...)
    from langgraph.types import interrupt

    resume_value = interrupt(payload)

    # 解析外部传入的决策 — Day 7: 兼容 approve/reject
    raw = parse_resume_decision(resume_value)
    decision = normalize_external_decision(raw) if raw else "reject"
    # 转换为 ReAct 内部决策 (proceed / abort)
    internal_decision: str = {"approve": "proceed", "reject": "abort"}.get(decision, "abort")

    return {
        "decision": internal_decision,
        "external_decision": decision,
        "reason": args.reason,
        "gate_id": gate_id,
        "reviewed_by": "human",
    }


request_human_review_tool = ToolDef(
    id="request_human_review",
    description=(
        "Request a human reviewer to proceed or abort the current workflow step. "
        "Pauses execution until a human approves (proceed) or rejects (abort). "
        "Call this when the routing layer triggers a HUMAN_GATE decision, or when "
        "the agent needs confirmation for a high-risk action."
    ),
    schema=HumanReviewArgs,
    execute=request_human_review_execute,
)

__all__ = ["request_human_review_tool", "HumanReviewArgs"]
