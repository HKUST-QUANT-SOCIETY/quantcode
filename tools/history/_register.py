"""Personal server history, independent of browser caches and LLM availability."""
from pydantic import BaseModel, Field

from runner.run_history import get_history, list_history
from tools.registry import ToolDef, registry


class ListHistoryArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1024)


class GetHistoryArgs(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    checkpoint_id: str | None = Field(default=None, max_length=128)
    trace_cursor: int = Field(default=0, ge=0)


for tool in (
    ToolDef(id="list_run_history", description="List this actor's persisted runs in the current group/workspace. Read-only and paginated; does not execute or resume tasks.",
            schema=ListHistoryArgs, execute=lambda args, ctx: list_history(ctx, **args.model_dump())),
    ToolDef(id="get_run_history", description="Read a persisted run or historical checkpoint with messages and artifacts. Does not execute or resume tasks.",
            schema=GetHistoryArgs, execute=lambda args, ctx: get_history(ctx, **args.model_dump())),
):
    tool._meta = True
    registry._tools[tool.id] = tool


class AdminHistoryArgs(ListHistoryArgs):
    group_filter: str | None = None


for tool in (
    ToolDef(id="admin_task_history", description="Admin organization task history from durable checkpoints, with mandatory read audit.",
            schema=AdminHistoryArgs, execute=lambda args, ctx: list_history(ctx, organization=True, **args.model_dump())),
    ToolDef(id="admin_report_history", description="Admin artifact/report reference index across organization tasks; does not publish or recompute reports.",
            schema=AdminHistoryArgs, execute=lambda args, ctx: list_history(ctx, organization=True, reports_only=True, **args.model_dump())),
    ToolDef(id="admin_get_task_history", description="Admin read-only checkpoint detail with mandatory audit before disclosure.",
            schema=GetHistoryArgs, execute=lambda args, ctx: get_history(ctx, organization=True, **args.model_dump())),
):
    tool._meta = True
    registry._tools[tool.id] = tool


class ListPendingGatesArgs(BaseModel):
    limit: int = Field(default=100, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=1024)


def _gates(args: ListPendingGatesArgs, ctx: dict) -> dict:
    from runner.run_history import list_pending_gates
    return list_pending_gates(ctx, **args.model_dump())


tool = ToolDef(id="list_pending_gates", description="Same-group approver/admin queue from durable checkpoints. Returns exact Gate IDs; reading never approves or resumes a task.", schema=ListPendingGatesArgs, execute=_gates)
tool._meta = True
registry._tools[tool.id] = tool
