"""request_human_review tool — 研报非阻断审阅标记（F-03 v0.2 收窄 / G2-A8）。

历史（Day 4 / Day 7）：本工具曾是 LangGraph 真阻断 interrupt——调用即经
``langgraph.types.interrupt()`` 暂停，等 ``Command(resume=...)`` 的人工决策。

2026-09-01 HumanGate 收窄为**写操作门禁**：研报产出人本来要看，由报告平台
承接，不再挂 Gate。本工具改为**非阻断审阅标记**：写 review_requested 标记
（随 tool_result 进 execution_trace 留痕）后直接放行，流程继续。
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from tools.registry import ToolDef


class HumanReviewArgs(BaseModel):
    """request_human_review 的参数。"""

    reason: str = ""


def request_human_review_execute(args: HumanReviewArgs, ctx: dict) -> str:
    """写审阅标记并直接放行（非阻断，零 interrupt）。

    返回 JSON **字符串**（而非 dict）是刻意的：agent_nodes._extract_state_fields
    只对 dict 输出做 state 注入，且对 request_human_review 会把
    ``output["decision"]``（缺省 "abort"）写进 state.human_review_result——
    审阅标记语义里不存在任何人工决策，字符串返回保证零 state 副作用。
    """
    marker = {
        "review_requested": True,
        "status": "review_requested",
        "reason": args.reason,
        "thread_id": str(ctx.get("thread_id") or ctx.get("source") or ""),
        "note": "研报审阅标记（非阻断）：产出由报告平台承接，流程继续",
    }
    return json.dumps(marker, ensure_ascii=False)


request_human_review_tool = ToolDef(
    id="request_human_review",
    description=(
        "Flag the current research output (e.g. a rendered report) as pending human "
        "review and continue. Non-blocking: it only records a review_requested marker "
        "for the report platform; it does NOT pause or gate the workflow. "
        "Only write operations into production surfaces require a HumanGate."
    ),
    schema=HumanReviewArgs,
    execute=request_human_review_execute,
)

__all__ = ["request_human_review_tool", "HumanReviewArgs"]
