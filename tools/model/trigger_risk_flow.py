"""trigger_risk_flow tool — 写入 PROJECT-scope risk handoff queue。"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from runner.blackboard import BlackboardService
from schemas import BlackboardScope, GroupName, WritePolicy
from tools.model.write_blackboard import _synthesize_task_id
from tools.registry import ToolDef
from tools.utils.dedupe import dedupe_within


class TriggerRiskFlowArgs(BaseModel):
    blackboard_key: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def trigger_risk_flow_execute(args: TriggerRiskFlowArgs, ctx: dict) -> dict:
    """把 pending risk review 写入 PROJECT scope，供 risk group 消费。

    读自 ctx：
    - ``thread_id`` / ``session_id`` — Blackboard session_id
    - ``group`` — 发起组，默认 model
    - ``task_id`` — 可选；缺省从 thread_id 派生
    - ``blackboard_db_path`` — 可选覆盖默认 db 路径
    """
    thread_id = (
        ctx.get("thread_id")
        or ctx.get("session_id")
        or "default-thread"
    )
    raw_group = ctx.get("group") or "model"
    from_group = GroupName(raw_group)
    task_id = ctx.get("task_id") or _synthesize_task_id(thread_id)
    db_path_str = ctx.get("blackboard_db_path")
    db_path = Path(db_path_str) if db_path_str else None

    service = BlackboardService(
        db_path=db_path,
        session_id=thread_id,
        requester_group=from_group,
    )
    source_entry = service.get_entry(
        BlackboardScope.PROJECT,
        None,
        args.blackboard_key,
        requester_group=from_group,
    )
    source_value: dict[str, Any] = (
        source_entry.value
        if source_entry is not None and isinstance(source_entry.value, dict)
        else {}
    )

    queue_key = "shared.pending_risk_reviews"
    existing = service.get_entry(
        BlackboardScope.PROJECT,
        None,
        queue_key,
        requester_group=from_group,
    )
    reviews: dict[str, Any] = {}
    if existing is not None and isinstance(existing.value, dict):
        raw_reviews = existing.value.get("reviews", {})
        if isinstance(raw_reviews, dict):
            reviews.update(raw_reviews)

    review_id = (
        source_value.get("pr_url")
        or source_value.get("commit_sha")
        or source_value.get("model_name")
        or args.blackboard_key
    )
    review = {
        "from_group": from_group.value,
        "to_group": GroupName.RISK.value,
        "status": "pending",
        "blackboard_key": args.blackboard_key,
        "model_name": source_value.get("model_name"),
        "pr_url": source_value.get("pr_url"),
        "commit_sha": source_value.get("commit_sha"),
        "triggered_at": _now_iso(),
    }
    reviews[str(review_id)] = review
    queue_entry = service.write_value(
        scope=BlackboardScope.PROJECT,
        key=queue_key,
        value={"reviews": reviews},
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id=task_id,
        written_by_group=from_group,
    )
    return {
        "risk_queue_key": queue_entry.key,
        "risk_queue_version": queue_entry.version,
        "review_id": str(review_id),
        "review": review,
    }


# 去重窗口 600 秒，scope 仅在 ``trigger_risk_flow_execute`` 这一个函数内。
# key 函数的签名匹配 execute 的签名 ``(args: TriggerRiskFlowArgs, ctx: dict)``。
trigger_risk_flow_wrapped_execute = dedupe_within(
    seconds=600,
    key=lambda args, ctx: f"{args.blackboard_key}",
)(trigger_risk_flow_execute)


trigger_risk_flow_tool = ToolDef(
    id="trigger_risk_flow",
    description=(
        "Queue a risk evaluation handoff in PROJECT scope under "
        "shared.pending_risk_reviews for the model/risk cross-group flow."
    ),
    schema=TriggerRiskFlowArgs,
    execute=trigger_risk_flow_wrapped_execute,
)

__all__ = [
    "trigger_risk_flow_tool",
    "TriggerRiskFlowArgs",
    "trigger_risk_flow_execute",
]
