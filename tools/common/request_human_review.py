"""request_human_review tool — 模拟人工审核。

调用 LLM 在 human_gate 之后主动调此 tool 采集人审结果。
当前 stub：随机返回 proceed/abort（模拟人工点击）。
Day 4 替换为真正的交互式审核。
"""
from __future__ import annotations

import random

from pydantic import BaseModel

from tools.registry import ToolDef


class HumanReviewArgs(BaseModel):
    """request_human_review 的参数。"""
    reason: str = ""


def request_human_review_execute(args: HumanReviewArgs, ctx: dict) -> dict:
    """Stub：随机 proceed/abort，模拟人工审核结果。

    Day 4 替换为真正的人机交互（如 CLI prompt、Web UI callback）。
    """
    decision = random.choice(["proceed", "abort"])
    return {
        "decision": decision,
        "reason": args.reason,
        "reviewed_by": "mock-human-reviewer",
        "note": f"Stub decision: {decision}. Day 4 replace with real human gate.",
    }


request_human_review_tool = ToolDef(
    id="request_human_review",
    description=(
        "Request a human reviewer to proceed or abort the current workflow step. "
        "Call this when the routing layer triggers a HUMAN_GATE decision. "
        "Returns {'decision': 'proceed'|'abort', ...}."
    ),
    schema=HumanReviewArgs,
    execute=request_human_review_execute,
)

__all__ = ["request_human_review_tool", "HumanReviewArgs"]
