"""Human-attested receipt repair, outside the model's tool catalog."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from runner.execution_lock import execution_lock
from runner.tool_receipts import decode_result, result_digest


class ReconcileReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    checkpoint_id: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=1, max_length=256)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["confirmed_completed", "confirmed_not_executed"]
    evidence_ref: str = Field(min_length=1, max_length=2000)
    note: str = Field(min_length=1, max_length=4000)
    result: Any = None


def reconcile(request: ReconcileReceipt, context: dict, checkpoint_db: Path) -> dict:
    if context.get("role") not in {"admin", "approver"} or not context.get("actor_id"):
        raise PermissionError("authenticated reviewer required")
    if not request.note.strip() or not request.evidence_ref.strip():
        raise ValueError("external evidence reference and review note are required")
    if request.decision == "confirmed_completed" and "result" not in request.model_fields_set:
        raise ValueError("verified original result is required")
    if request.decision == "confirmed_not_executed" and "result" in request.model_fields_set:
        raise ValueError("a non-executed operation cannot have a result")
    receipts = checkpoint_db.with_suffix(".tool-receipts.db")
    if not checkpoint_db.is_file() or not receipts.is_file():
        raise PermissionError("task receipt not found")
    # Same task/operation locks as MCP execution. Review cannot change a receipt
    # while a live invocation may still commit its actual result.
    with execution_lock(checkpoint_db, request.thread_id), execution_lock(receipts, f"{request.thread_id}:{request.call_id}"):
        with sqlite3.connect(f"{checkpoint_db.resolve().as_uri()}?mode=ro", uri=True) as source:
            row = source.execute("SELECT checkpoint_id,type,checkpoint FROM checkpoints WHERE thread_id=? AND checkpoint_ns='' ORDER BY checkpoint_id DESC LIMIT 1", (request.thread_id,)).fetchone()
        if not row or row[0] != request.checkpoint_id:
            raise ValueError("checkpoint changed; reload the task before review")
        saved = JsonPlusSerializer().loads_typed((row[1], row[2]))["channel_values"]
        if not context.get("group") or saved.get("group") != context["group"]:
            raise PermissionError("review requires the task's group")
        with sqlite3.connect(receipts) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            if not any(row[1] == "result_digest" for row in conn.execute("PRAGMA table_info(tool_receipts)")):
                conn.execute("ALTER TABLE tool_receipts ADD COLUMN result_digest TEXT")
            prior = conn.execute("SELECT digest,status,kind,result,result_digest FROM tool_receipts WHERE thread=? AND call_id=?", (request.thread_id, request.call_id)).fetchone()
            if not prior or prior[0] != request.expected_digest:
                raise ValueError("receipt changed or not found")
            if prior[1] == "RETRY_ALLOWED":
                raise ValueError("receipt already reviewed; reload the task")
            if prior[1] == "COMPLETED":
                try:
                    decode_result(prior[2], prior[3], prior[4])
                except Exception:
                    if request.decision != "confirmed_completed":
                        raise ValueError("unreadable completed receipt requires result recovery, not re-execution")
                else:
                    raise ValueError("a valid completed result cannot be replaced")
            status = "COMPLETED" if request.decision == "confirmed_completed" else "RETRY_ALLOWED"
            kind, payload = JsonPlusSerializer().dumps_typed(request.result) if status == "COMPLETED" else (None, None)
            audit = {**request.model_dump(exclude={"result"}), "reviewer": context["actor_id"],
                     "original_result_digest": prior[4],
                     "reviewer_session": context.get("session_id"), "status": status,
                     "result_digest": hashlib.sha256(payload).hexdigest() if payload is not None else None,
                     "reviewed_at": datetime.now(timezone.utc).isoformat(), "review_id": uuid4().hex}
            conn.execute("CREATE TABLE IF NOT EXISTS receipt_reviews (review_id TEXT PRIMARY KEY, payload TEXT NOT NULL, original_status TEXT, original_kind TEXT, original_result BLOB)")
            from runner.evidence import EVIDENCE_DIR, append_event
            append_event(request.thread_id, "output_data", {"receipt_review_intent": audit}, EVIDENCE_DIR, required=True)
            conn.execute("INSERT INTO receipt_reviews VALUES(?,?,?,?,?)", (audit["review_id"], json.dumps(audit), prior[1], prior[2], prior[3]))
            conn.execute("UPDATE tool_receipts SET status=?,kind=?,result=?,result_digest=? WHERE thread=? AND call_id=?", (status, kind, payload, result_digest(kind, payload) if payload is not None else None, request.thread_id, request.call_id))
        return {"review": audit, "execution_started": False}
