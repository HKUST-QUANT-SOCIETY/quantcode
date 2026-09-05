"""stream tools — check_tool_stream：按游标读 run 事件通道（attach_stream 消费端）。

import 即触发 1 个 ToolDef 注册（与 tools/subagent/_register.py 风格一致）：
- check_tool_stream(run_id, cursor, wait_s) — 增量读 ``.quantcode/streams/<run_id>.jsonl``

权限边界：**元工具**（_meta=True），只读无副作用，不进各组 tool_allowlist，
经 mcp_server._meta 通道仅向控制器（OpenCode compose / monitor）暴露——
与 check_subagent 同路，子 agent 不应消费自己的事件流。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from tools.registry import ToolDef, registry


class CheckToolStreamArgs(BaseModel):
    """check_tool_stream 入参。"""

    run_id: str = Field(
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
        description="run_agent start 返回的 opaque thread_id（= run_id）。",
    )
    cursor: int = Field(default=0, ge=0, description="行偏移游标（上次 read_from 返回的 next_cursor，首读传 0）。")
    wait_s: int = Field(default=0, ge=0, le=120, description=">0 时轮询阻塞至有新事件或超时（秒）。")


def _check_tool_stream_execute(args: CheckToolStreamArgs, ctx: dict) -> dict:
    import time as _time

    from runner.stream_channel import read_from

    # A meta tool is discoverable, not public. Resolve ownership from the
    # persisted checkpoint; knowing a thread id never grants access to its trace.
    if ctx.get("role") is not None:
        from runner.langgraph_base import CHECKPOINTS_DB, get_checkpointer

        checkpoint = get_checkpointer(ctx.get("_checkpoint_db") or CHECKPOINTS_DB).get_tuple(
            {"configurable": {"thread_id": args.run_id, "checkpoint_ns": ""}}
        )
        values = checkpoint.checkpoint.get("channel_values", {}) if checkpoint else {}
        if not values:
            raise PermissionError("stream has no authenticated owner checkpoint")
        if ctx.get("role") != "admin":
            for field in ("actor_id", "group", "workspace_id", "workspace_path"):
                if not ctx.get(field) or values.get(field) != ctx.get(field):
                    raise PermissionError("stream is outside the current actor/workspace scope")

    deadline = args.wait_s if args.wait_s and args.wait_s > 0 else 0
    waited = 0.0
    interval = 0.1
    while True:
        result = read_from(args.run_id, args.cursor)
        has_new = bool(result.get("events")) or result.get("exists") is False
        if has_new or waited >= deadline:
            return result
        _time.sleep(interval)
        waited += interval


check_tool_stream_tool = ToolDef(
    id="check_tool_stream",
    description=(
        "Incremental read of an agent run's event stream (attach_stream=true runs "
        "append execution_trace events to .quantcode/streams/<run_id>.jsonl). "
        "Returns {events, next_cursor, exists}: pass next_cursor back as cursor "
        "for the next poll; exists=false means no stream for this run_id "
        "(run wasn't started with attach_stream). wait_s>0 blocks until new "
        "events appear or timeout."
    ),
    schema=CheckToolStreamArgs,
    execute=_check_tool_stream_execute,
)

# 元工具：只读，经 _meta 通道暴露（不进 allowlist，不供子 agent 递归消费）。
check_tool_stream_tool._meta = True  # type: ignore[attr-defined]

registry._tools[check_tool_stream_tool.id] = check_tool_stream_tool  # 幂等覆盖（reload 安全）


__all__ = ["check_tool_stream_tool", "CheckToolStreamArgs"]
