"""read_pr tool — 读取 GitHub PR diff（mock 实现）。"""
from __future__ import annotations

from pydantic import BaseModel

from tools.registry import ToolDef


class ReadPRArgs(BaseModel):
    pr_number: int


def read_pr_execute(args: ReadPRArgs, ctx: dict) -> dict:
    # Mock: 返回一个固定格式的假 diff
    return {
        "pr_number": args.pr_number,
        "diff": (
            f"--- a/fake_file.py\n+++ b/fake_file.py\n"
            f"@@ -1,3 +1,3 @@\n"
            f"-fake line {args.pr_number - 1}\n"
            f"+fake line {args.pr_number}\n"
        ),
        "title": f"[MOCK] PR #{args.pr_number}",
        "author": "mock-user",
    }


read_pr_tool = ToolDef(
    id="read_pr",
    description=(
        "Read the diff of a GitHub PR by number. "
        "Returns {pr_number, diff, title, author}."
    ),
    schema=ReadPRArgs,
    execute=read_pr_execute,
)

__all__ = ["read_pr_tool", "ReadPRArgs", "read_pr_execute"]