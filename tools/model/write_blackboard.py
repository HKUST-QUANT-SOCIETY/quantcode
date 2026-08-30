"""write_blackboard tool — 持久化 key→value 到 BlackboardService。

Day 3 评审后改造（leader 指令 2）：
- tools/model/ 内的 mock 实现不再完善；底座（ToolDef/Registry/MCP）保持
- 真持久化交给从 PR #18 (shawchen5242) cherry-pick 的 runner/blackboard.py
- 写入 PROJECT scope：跨组可见 handoff。GROUP 私有持久化由需要私有状态的
  group tool 另行显式写入，model handoff 不再无条件双写。

写入流程：
1. 用 ctx 里的 thread_id 当 session_id，group 当 requester_group
2. 构造 BlackboardService（默认 db_path = .quantcode/blackboard.db）
3. 调 write_value 写 PROJECT scope（cross-group 共享）
4. 返回 BlackboardEntry.model_dump()

注：BlackboardEntry.written_by_task_id 受 schemas.compose_task 的 TASK_ID_PATTERN
约束（``^T\\d+(\\.\\d+){0,4}$``）。ReAct loop 暂无真正的 task_id，这里从 thread_id
派生一个稳定的合成 task_id（``T1.{thread_hash}``），后续接入 ComposeTask 时
由 tool_node 注入真正的 task_id 替换。
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from runner.blackboard import BlackboardService
from runner.blackboard_keys import PROJECT_SESSION_ID, make_read_key
from schemas import BlackboardEntry, BlackboardScope, GroupName, WritePolicy
from tools.registry import ToolDef
from tools.utils.dedupe import dedupe_within


class WriteBlackboardArgs(BaseModel):
    key: str
    value: dict


def _synthesize_task_id(thread_id: str) -> str:
    """从 thread_id 派生一个稳定的合成 task_id（满足 TASK_ID_PATTERN ``^T\\d+(\\.\\d+){0,4}$``）。

    规则：``T1.<digits8>``，其中 digits8 是 thread_id 的稳定 8 位数字摘要
    （取 sha1 hex 后只保留数字字符，不足 8 位补 0）。
    """
    import hashlib

    hex_digest = hashlib.sha1(thread_id.encode("utf-8")).hexdigest()
    digits_only = "".join(ch for ch in hex_digest if ch.isdigit())
    segment = (digits_only + "0" * 8)[:8]
    return f"T1.{segment}"


def write_blackboard_execute(args: WriteBlackboardArgs, ctx: dict) -> dict:
    """写一个 dict 值到 blackboard 的 PROJECT scope。

    读自 ctx：
    - ``thread_id`` (或 ``session_id``) — 仅用于派生合成 task_id 与 dedupe
    - ``group`` — 写者所在 group
    - ``task_id`` — 真实 task_id（可选，缺省从 thread_id 派生）
    - ``blackboard_db_path`` — 可选覆盖默认 db 路径

    构造 BlackboardService，调 ``write_value``：
    - session 固定 ``PROJECT_SESSION_ID``（跨组共享条目归一层，P0-2）
    - PROJECT scope：key 经 ``make_read_key`` 归一（裸名补 ``shared.model_entries.``
      前缀，幂等），跨组可读

    返回：
        ``{"project_entry": {...}}``，即 BlackboardEntry 的 dict 形式
        （含 scope/key/value/version/created_at 等）。
    """
    thread_id = (
        ctx.get("thread_id")
        or ctx.get("session_id")
        or "default-thread"
    )
    raw_group = ctx.get("group") or "model"
    group: GroupName = GroupName(raw_group)

    task_id = ctx.get("task_id") or _synthesize_task_id(thread_id)

    db_path_str = ctx.get("blackboard_db_path")
    db_path = Path(db_path_str) if db_path_str else None

    service = BlackboardService(
        db_path=db_path,
        session_id=PROJECT_SESSION_ID,
        requester_group=group,
    )

    project_entry: BlackboardEntry = service.write_value(
        scope=BlackboardScope.PROJECT,
        key=make_read_key(args.key),
        value=args.value,
        write_policy=WritePolicy.GROUP_APPEND,
        written_by_task_id=task_id,
        written_by_group=group,
    )
    return {
        "project_entry": project_entry.model_dump(mode="json"),
    }


# 去重窗口 300 秒，scope 仅在 ``write_blackboard_execute`` 这一个函数内。
# 防短时间重复写入（同一 key 在 5 分钟内只首次真正落盘，后续返回上一次结果）。
write_blackboard_wrapped_execute = dedupe_within(
    seconds=300,
    key=lambda args, ctx: f"{ctx.get('thread_id', 'default')}::{args.key}",
)(write_blackboard_execute)


write_blackboard_tool = ToolDef(
    id="write_blackboard",
    description=(
        "Write a value dict to the blackboard under the given key. "
        "Persists via BlackboardService (cherry-picked from PR #18 shawchen5242) "
        "to PROJECT scope for cross-group handoff."
    ),
    schema=WriteBlackboardArgs,
    execute=write_blackboard_wrapped_execute,
)

__all__ = [
    "write_blackboard_tool",
    "WriteBlackboardArgs",
    "write_blackboard_execute",
]
