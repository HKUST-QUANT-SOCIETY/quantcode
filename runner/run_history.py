"""Read-only, identity-scoped history from the authoritative checkpoint store.

History never invokes a graph, infers project grants, or treats an unfinished
checkpoint as a running process. Personal history stays personal for Admin too;
organization-wide monitoring is a separate, audited product surface.
"""
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from runner.langgraph_base import CHECKPOINTS_DB
from schemas.groups import GROUP_IDS


def _identity(ctx: dict) -> None:
    if ctx.get("role") not in {"analyst", "approver", "admin"} or ctx.get("group") not in GROUP_IDS:
        raise PermissionError("authenticated Session Context is required for history")
    if any(not ctx.get(key) for key in ("actor_id", "workspace_id", "workspace_path")):
        raise PermissionError("history requires an authenticated actor and workspace")


def _owned(values: dict, ctx: dict) -> bool:
    return all(values.get(key) == ctx.get(key) for key in (
        "actor_id", "group", "workspace_id", "workspace_path",
    ))


def _connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    # Existing but unreadable/corrupt databases must produce a service error,
    # not an empty history that invites the user to repeat completed work.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _decode(row: tuple) -> tuple[dict, dict]:
    checkpoint = JsonPlusSerializer().loads_typed((row[2], row[3]))
    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("channel_values"), dict):
        raise ValueError("invalid history checkpoint")
    return checkpoint, checkpoint["channel_values"]


def _summary(row: tuple, checkpoint: dict, values: dict) -> dict:
    data = values.get("input_data") or {}
    return {
        "thread_id": row[0], "checkpoint_id": row[1],
        "timestamp": checkpoint.get("ts"),
        "task": str(data.get("task") or "")[:500] if isinstance(data, dict) else "",
        "group": values.get("group"), "actor_id": values.get("actor_id"),
        "workspace_id": values.get("workspace_id"),
        # The persisted graph state proves completion, but cannot prove a
        # process is currently running or that side effects are safe to retry.
        "status": "completed" if values.get("task_status") == "done" else "checkpoint_saved",
        "iterations": values.get("iterations", 0),
    }


def _cursor_before(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        before = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(before, list) or len(before) != 2 or not all(isinstance(x, str) for x in before):
            raise ValueError()
        return tuple(before)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("invalid history cursor") from exc


def _next_cursor(items: list[dict], more: bool) -> str | None:
    if not more or not items:
        return None
    return base64.urlsafe_b64encode(json.dumps([
        items[-1]["checkpoint_id"], items[-1]["thread_id"],
    ]).encode()).decode()


def list_history(ctx: dict, *, limit: int = 20, cursor: str | None = None,
                 db_path: Path = CHECKPOINTS_DB, organization: bool = False,
                 reports_only: bool = False, group_filter: str | None = None) -> dict:
    _identity(ctx)
    if organization and ctx.get("role") != "admin":
        raise PermissionError("organization history requires Admin")
    if group_filter and group_filter not in GROUP_IDS:
        raise ValueError("invalid group filter")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    before = _cursor_before(cursor)
    conn = _connect(Path(db_path))
    if conn is None:
        return {"runs": [], "next_cursor": None}
    try:
        rows = conn.execute(
            "SELECT c.thread_id, c.checkpoint_id, c.type, c.checkpoint "
            "FROM checkpoints c JOIN (SELECT thread_id, MAX(checkpoint_id) latest "
            "FROM checkpoints WHERE checkpoint_ns = '' GROUP BY thread_id) newest "
            "ON c.thread_id = newest.thread_id AND c.checkpoint_id = newest.latest "
            "WHERE c.checkpoint_ns = '' ORDER BY c.checkpoint_id DESC, c.thread_id DESC"
        )
        runs = []
        for row in rows:
            if before and (row[1], row[0]) >= tuple(before):
                continue
            checkpoint, values = _decode(row)
            if not organization and not _owned(values, ctx):
                continue
            if group_filter and values.get("group") != group_filter:
                continue
            artifacts = values.get("artifacts") or []
            if reports_only and not artifacts:
                continue
            summary = _summary(row, checkpoint, values)
            summary["artifacts"] = artifacts
            runs.append(summary)
            if len(runs) > limit:
                break
        more = len(runs) > limit
        runs = runs[:limit]
        next_cursor = _next_cursor(runs, more)
        result = {"runs": runs, "next_cursor": next_cursor}
        if organization:
            from runner.admin_scope import audited_read_result
            return audited_read_result("admin_report_history" if reports_only else "admin_task_history", ctx, result)
        return result
    finally:
        conn.close()


def get_history(ctx: dict, *, thread_id: str, checkpoint_id: str | None = None,
                trace_cursor: int = 0,
                db_path: Path = CHECKPOINTS_DB, organization: bool = False) -> dict[str, Any]:
    _identity(ctx)
    if organization and ctx.get("role") != "admin":
        raise PermissionError("organization history requires Admin")
    conn = _connect(Path(db_path))
    if conn is None:
        raise PermissionError("history not found in the current scope")
    try:
        # Always authorize the latest owner before allowing a historical
        # checkpoint selection; old revisions never become alternate grants.
        latest = conn.execute(
            "SELECT thread_id, checkpoint_id, type, checkpoint FROM checkpoints "
            "WHERE thread_id = ? AND checkpoint_ns = '' ORDER BY checkpoint_id DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if latest is None:
            raise PermissionError("history not found in the current scope")
        checkpoint, values = _decode(latest)
        if not organization and not _owned(values, ctx):
            raise PermissionError("history not found in the current scope")
        row = latest
        if checkpoint_id:
            row = conn.execute(
                "SELECT thread_id, checkpoint_id, type, checkpoint FROM checkpoints "
                "WHERE thread_id = ? AND checkpoint_ns = '' AND checkpoint_id = ?",
                (thread_id, checkpoint_id),
            ).fetchone()
            if row is None:
                raise PermissionError("history not found in the current scope")
            checkpoint, values = _decode(row)
            if not organization and not _owned(values, ctx):
                raise PermissionError("history not found in the current scope")
        from runner.agent_mcp_tool import _format_result

        result = _format_result(values, str(values.get("group") or ""))
        result.update(_summary(row, checkpoint, values))
        result["read_only"] = True
        pending = conn.execute(
            "SELECT type,value FROM writes WHERE thread_id=? AND checkpoint_ns='' AND checkpoint_id=? AND channel='__interrupt__'",
            (thread_id, row[1]),
        ).fetchall()
        result["pending_approval"] = bool(pending)
        result["can_resume"] = bool(row[1] == latest[1] and _owned(values, ctx)
                                    and values.get("task_status") != "done" and not pending
                                    and all(values.get(field) == ctx.get(field) for field in ("role", "github_subject"))
                                    and set(values.get("resource_scopes") or []) == set(ctx.get("resource_scopes") or []))
        result["recovery_note"] = "Recovery revalidates ownership, pending approvals and the latest checkpoint; historical viewing never starts execution."
        from runner.tool_receipts import unresolved_receipts, receipt_reviews
        try:
            unresolved = unresolved_receipts(Path(db_path).with_suffix(".tool-receipts.db"), thread_id)
        except (OSError, sqlite3.Error, ValueError):
            unresolved = []
            result["can_resume"] = False
            result["recovery_block_reason"] = "工具回执存储不可读；历史仍可查看，但修复回执前不能恢复执行。"
        try:
            result["receipt_reviews"] = receipt_reviews(Path(db_path).with_suffix(".tool-receipts.db"), thread_id)
        except (OSError, sqlite3.Error, ValueError):
            result["receipt_reviews"] = []
            result["receipt_review_error"] = "已提交审核记录暂不可读，请检查回执存储；空列表不代表没有审核。"
        tool_names = {call.get("id"): call.get("name")
                      for message in values.get("messages", [])
                      for call in (getattr(message, "tool_calls", None) or []) if isinstance(call, dict)}
        result["unresolved_operations"] = [{**item, "tool": tool_names.get(item["call_id"])} for item in unresolved]
        if unresolved:
            result["can_resume"] = False
            result["recovery_block_reason"] = "有工具调用尚无可读的完成回执；需先核对外部结果，不能自动恢复或重新执行。"
        if result["can_resume"]:
            from tools.skills.loader import validate_execution_skill
            try:
                validate_execution_skill(values)
            except Exception as exc:
                result["can_resume"] = False
                result["recovery_block_reason"] = (
                    str(exc) if isinstance(exc, PermissionError)
                    else "Skill 来源当前不可用，请恢复有效版本或用当前方案新建任务。"
                )
        from runner.stream_channel import read_from
        result["timeline"] = read_from(thread_id, trace_cursor, limit=100)

        result["messages"] = [
            {"type": getattr(message, "type", "unknown"),
             "content": getattr(message, "content", ""),
             "tool_calls": getattr(message, "tool_calls", [])}
            for message in values.get("messages", [])
        ]
        result["checkpoints"] = [item[0] for item in conn.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ? "
            "AND checkpoint_ns = '' ORDER BY checkpoint_id DESC LIMIT 100", (thread_id,),
        )]
        if organization:
            from runner.admin_scope import audited_read_result
            return audited_read_result("admin_get_task_history", ctx, result)
        return result
    finally:
        conn.close()


def list_pending_gates(ctx: dict, *, limit: int = 100, cursor: str | None = None,
                       db_path: Path = CHECKPOINTS_DB) -> dict:
    """Same-group reviewer queue with the exact persisted gate and checkpoint."""
    _identity(ctx)
    if ctx.get("role") not in {"approver", "admin"}:
        raise PermissionError("approval queue requires approver or admin")
    if not 1 <= limit <= 200:
        raise ValueError("invalid approval queue limit")
    before = _cursor_before(cursor)
    conn = _connect(Path(db_path))
    if conn is None:
        return {"gates": [], "has_more": False, "next_cursor": None}
    try:
        from runner.human_gate import pending_gate_from_writes
        rows = conn.execute("SELECT c.thread_id,c.checkpoint_id,c.type,c.checkpoint FROM checkpoints c "
                            "JOIN (SELECT thread_id,MAX(checkpoint_id) latest FROM checkpoints WHERE checkpoint_ns='' GROUP BY thread_id) n "
                            "ON c.thread_id=n.thread_id AND c.checkpoint_id=n.latest "
                            "WHERE c.checkpoint_ns='' ORDER BY c.checkpoint_id DESC,c.thread_id DESC")
        gates = []
        for row in rows:
            if before and (row[1], row[0]) >= before:
                continue
            checkpoint, values = _decode(row)
            if values.get("group") != ctx["group"]:
                continue
            writes = [(task, channel, JsonPlusSerializer().loads_typed((kind, blob)))
                      for task, channel, kind, blob in conn.execute(
                          "SELECT task_id,channel,type,value FROM writes WHERE thread_id=? AND checkpoint_ns='' AND checkpoint_id=? AND channel='__interrupt__'",
                          (row[0], row[1]))]
            gate = pending_gate_from_writes(writes)
            if gate is None:
                continue
            gates.append({**_summary(row, checkpoint, values), "gate": gate})
            if len(gates) > limit:
                break
        more = len(gates) > limit
        gates = gates[:limit]
        result = {"gates": gates, "has_more": more, "next_cursor": _next_cursor(gates, more)}
        from runner.admin_scope import audited_read_result
        return audited_read_result("list_pending_gates", ctx, result)
    finally:
        conn.close()
