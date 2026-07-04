"""trigger_risk_flow tool — 触发 risk 流程（mock 实现，带 dedupe）。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel

from tools.registry import ToolDef
from tools.utils.dedupe import dedupe_within


class TriggerRiskFlowArgs(BaseModel):
    blackboard_key: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def trigger_risk_flow_execute(args: TriggerRiskFlowArgs, ctx: dict) -> dict:
    """Mock：返回一个 ``risk-flow-{{uuid4 hex[:8]}}`` 形式的 flow_id。

    真正的 trigger（Day 4）会换成调用 risk group 的入口。
    """
    return {
        "flow_id": f"risk-flow-{uuid.uuid4().hex[:8]}",
        "triggered_at": _now_iso(),
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
        "Trigger a risk evaluation flow that reads blackboard data under "
        "``blackboard_key``. Mock: returns {flow_id, triggered_at}."
    ),
    schema=TriggerRiskFlowArgs,
    execute=trigger_risk_flow_wrapped_execute,
)

__all__ = [
    "trigger_risk_flow_tool",
    "TriggerRiskFlowArgs",
    "trigger_risk_flow_execute",
]