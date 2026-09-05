"""Durable replay receipts for side-effecting graph tool calls.

The receipt is committed before execution starts. A crash after the side effect
but before its result commit is uncertain, never permission to execute it again.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.errors import GraphInterrupt
from runner.execution_lock import execution_lock


class ToolOutcomeUnknown(RuntimeError):
    """Execution must stop until the actual external outcome is reconciled."""


def result_digest(kind: str, payload: bytes) -> str:
    return hashlib.sha256(kind.encode() + b"\0" + payload).hexdigest()


def decode_result(kind, payload, digest):
    if not digest or result_digest(kind, payload) != digest:
        raise ValueError("receipt result integrity cannot be verified")
    return JsonPlusSerializer().loads_typed((kind, payload))


def receipt_reviews(database: Path, thread_id: str) -> list[dict]:
    """Return committed human review records, after caller authorizes history."""
    if not database.exists():
        return []
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipt_reviews'").fetchone():
            return []
        rows = conn.execute(
            "SELECT payload FROM receipt_reviews WHERE json_extract(payload,'$.thread_id')=? "
            "ORDER BY json_extract(payload,'$.reviewed_at'),review_id", (thread_id,),
        )
        return [json.loads(row[0]) for row in rows]


def unresolved_receipts(database: Path, thread_id: str) -> list[dict]:
    """Read-only inspection; callers must authorize the task before disclosure."""
    if not database.exists():
        return []
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_receipts'").fetchone():
            return []
        result = []
        checksum = "result_digest" if any(row[1] == "result_digest" for row in conn.execute("PRAGMA table_info(tool_receipts)")) else "NULL"
        for call_id, digest, status, kind, payload, stored_digest in conn.execute(
            f"SELECT call_id,digest,status,kind,result,{checksum} FROM tool_receipts WHERE thread=? ORDER BY call_id", (thread_id,),
        ):
            if status == "RETRY_ALLOWED":
                continue
            if status == "COMPLETED":
                try:
                    decode_result(kind, payload, stored_digest)
                    continue
                except Exception:
                    status = "UNREADABLE_RESULT"
            result.append({"call_id": call_id, "digest": digest, "receipt_status": status})
        return result


def execute_once(database: Path, call: dict, context: dict, execute):
    thread = context.get("thread_id")
    call_id = call.get("id")
    if not thread or not call_id:
        raise ValueError("durable tool execution requires thread and call IDs")
    identity = {key: context.get(key) for key in (
        "actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject", "resource_scopes",
    )}
    identity["resource_scopes"] = sorted(identity.get("resource_scopes") or [])
    digest = hashlib.sha256(json.dumps([call["name"], call["args"], identity], sort_keys=True).encode()).hexdigest()
    database.parent.mkdir(parents=True, exist_ok=True)
    with execution_lock(database, f"{thread}:{call_id}"), sqlite3.connect(database) as conn:
        database.chmod(0o600)
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS tool_receipts (thread TEXT, call_id TEXT, digest TEXT NOT NULL, status TEXT NOT NULL, kind TEXT, result BLOB, PRIMARY KEY(thread,call_id))")
        if not any(row[1] == "result_digest" for row in conn.execute("PRAGMA table_info(tool_receipts)")):
            conn.execute("ALTER TABLE tool_receipts ADD COLUMN result_digest TEXT")
        row = conn.execute("SELECT digest,status,kind,result,result_digest FROM tool_receipts WHERE thread=? AND call_id=?", (thread, call_id)).fetchone()
        if row:
            if row[0] != digest:
                raise ToolOutcomeUnknown("工具调用标识已存在，但参数或身份不同；禁止覆盖原执行回执。")
            if row[1] == "COMPLETED":
                try:
                    return decode_result(row[2], row[3], row[4])
                except Exception as exc:
                    raise ToolOutcomeUnknown("工具完成回执不可读；禁止把读取失败当作重新执行的依据。") from exc
            if row[1] != "RETRY_ALLOWED":
                raise ToolOutcomeUnknown(f"工具调用 {call_id} 的外部执行结果不明；请核对原操作，不能自动重试。")
            conn.execute("UPDATE tool_receipts SET status='STARTED' WHERE thread=? AND call_id=?", (thread, call_id))
        else:
            conn.execute("INSERT INTO tool_receipts(thread,call_id,digest,status) VALUES(?,?,?,'STARTED')", (thread, call_id, digest))
        conn.commit()
        try:
            output = execute()
            kind, data = JsonPlusSerializer().dumps_typed(output)
            conn.execute("UPDATE tool_receipts SET status='COMPLETED',kind=?,result=?,result_digest=? WHERE thread=? AND call_id=?", (kind, data, result_digest(kind, data), thread, call_id))
            conn.commit()
            return output
        except GraphInterrupt:
            # Supported HumanGates occur before the protected side effect.
            # Resume must revisit that interrupt, not replay a terminal result.
            conn.execute("DELETE FROM tool_receipts WHERE thread=? AND call_id=?", (thread, call_id))
            conn.commit()
            raise
        except Exception as exc:
            raise ToolOutcomeUnknown(f"工具调用 {call_id} 未形成完成回执；请核对外部结果后再继续。") from exc
