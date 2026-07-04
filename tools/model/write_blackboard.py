"""write_blackboard tool — 把数据写入 blackboard（mock 实现，带 dedupe）。"""
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from tools.registry import ToolDef
from tools.utils.dedupe import dedupe_within


class WriteBlackboardArgs(BaseModel):
    key: str
    value: dict


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_blackboard_execute(args: WriteBlackboardArgs, ctx: dict) -> dict:
    """Mock：把 value 原样回显，外加时间戳。

    真正的 blackboard 写入逻辑（Day 4）会替换这里的 echo。
    """
    return {
        "key": args.key,
        "written": True,
        "timestamp": _now_iso(),
    }


# 去重窗口 300 秒，scope 仅在 ``write_blackboard_execute`` 这一个函数内。
# key 函数的签名匹配 execute 的签名 ``(args: WriteBlackboardArgs, ctx: dict)``。
write_blackboard_wrapped_execute = dedupe_within(
    seconds=300,
    key=lambda args, ctx: f"{args.key}",
)(write_blackboard_execute)


write_blackboard_tool = ToolDef(
    id="write_blackboard",
    description=(
        "Write a value dict to the blackboard under the given key. "
        "Mock: echoes {key, written=true, timestamp}."
    ),
    schema=WriteBlackboardArgs,
    execute=write_blackboard_wrapped_execute,
)

__all__ = [
    "write_blackboard_tool",
    "WriteBlackboardArgs",
    "write_blackboard_execute",
]