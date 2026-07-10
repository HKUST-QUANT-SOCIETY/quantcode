"""mark_task_done tool — LLM 主动标记任务完成。"""
from __future__ import annotations

from pydantic import BaseModel

from tools.registry import ToolDef


class MarkTaskDoneArgs(BaseModel):
    """mark_task_done 的参数（可选 summary 字段）。"""
    summary: str = ""


def mark_task_done_execute(args: MarkTaskDoneArgs, ctx: dict) -> dict:
    """返回确认，触发 _extract_state_fields 注入 task_status="done" 到 state。"""
    return {"status": "done", "message": f"Task marked as complete: {args.summary}"}


mark_task_done_tool = ToolDef(
    id="mark_task_done",
    description=(
        "Call this tool when the agent believes the task has been fully completed. "
        "This will inject task_status='done' into the state, allowing the routing "
        "layer to trigger a FINISH decision."
    ),
    schema=MarkTaskDoneArgs,
    execute=mark_task_done_execute,
)

__all__ = ["mark_task_done_tool", "MarkTaskDoneArgs"]
