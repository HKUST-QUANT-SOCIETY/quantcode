"""Legacy model usage inspection and human-attested repair, outside tool catalogs."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import uuid4

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from runner.evidence import append_event
from runner.execution_lock import execution_lock
from runner.run_history import legacy_checkpoint_binding


class UsageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UsageReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: StrictInt = Field(ge=0)
    output_tokens: StrictInt = Field(ge=0)
    tokens: StrictInt = Field(ge=0)
    cost: float | None = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_total(self):
        if self.tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total usage must include input and output")
        return self


class UsageReview(UsageRead):
    checkpoint_id: str = Field(min_length=1, max_length=128)
    checkpoint_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_stopped: Literal[True]
    decision: Literal["usage_confirmed", "confirmed_not_executed"]
    receipt: UsageReceipt | None = None
    evidence_ref: str = Field(min_length=1, max_length=2000)
    note: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_decision(self):
        if not self.evidence_ref.strip() or not self.note.strip():
            raise ValueError("external evidence and a review note are required")
        if (self.decision == "usage_confirmed") != (self.receipt is not None):
            raise ValueError("usage_confirmed requires a receipt; confirmed_not_executed accepts none")
        return self


def _ledger(database: Path) -> Path:
    path = database.with_suffix(".legacy-usage.db")
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise PermissionError("legacy usage store must be canonical")
    if path.exists():
        info = path.stat()
        if not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError("legacy usage store must be private")
    return path


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _requests(conn: sqlite3.Connection, thread_id: str, owner_digest: str) -> list[dict]:
    rows = conn.execute("SELECT request_id,provider,model,created,reserved,input,output,total,cost FROM legacy_model_usage WHERE thread_id=? ORDER BY created,request_id", (thread_id,)).fetchall()
    result = []
    for row in rows:
        original = dict(zip(("request_id", "provider", "model", "created", "reserved_tokens", "input_tokens", "output_tokens", "tokens", "cost"), row))
        original.update(thread_id=thread_id, owner_digest=owner_digest)
        result.append({**original, "reservation_digest": _digest(original),
                       "status": "unconfirmed" if row[7] is None else "settled"})
    return result


def usage_state(database: Path, thread_id: str, owner_digest: str) -> dict:
    path = _ledger(database)
    empty = {"used_tokens": 0, "reserved_tokens": 0, "unconfirmed_requests": 0, "requests": 0, "cost": None}
    if not path.exists():
        return empty
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT owner_digest,baseline FROM legacy_usage_owner WHERE thread_id=?", (thread_id,)).fetchone()
        if row is None:
            if conn.execute("SELECT 1 FROM legacy_model_usage WHERE thread_id=? LIMIT 1", (thread_id,)).fetchone():
                raise ValueError("legacy model requests have no matching owner record")
            return empty
        if row[0] != owner_digest:
            raise PermissionError("legacy model usage belongs to another checkpoint owner")
        rows = _requests(conn, thread_id, owner_digest)
        return {"used_tokens": row[1] + sum(item["tokens"] or 0 for item in rows),
                "reserved_tokens": sum(item["reserved_tokens"] for item in rows if item["tokens"] is None),
                "unconfirmed_requests": sum(item["tokens"] is None for item in rows), "requests": len(rows),
                "cost": sum(item["cost"] for item in rows) if row[1] == 0 and rows and all(item["cost"] is not None for item in rows) else None}


def _binding(context: dict, database: Path, thread_id: str) -> dict:
    if context.get("role") not in {"admin", "approver"} or not context.get("actor_id"):
        raise PermissionError("legacy usage review requires an authenticated reviewer")
    # Like existing tool receipt reconciliation, only Admin or a same-group
    # reviewer may inspect another member's exact task accounting.
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT type,checkpoint FROM checkpoints WHERE thread_id=? AND checkpoint_ns='' ORDER BY checkpoint_id DESC LIMIT 1", (thread_id,)).fetchone()
    if not row:
        raise PermissionError("legacy task is unavailable in this scope")
    saved = JsonPlusSerializer().loads_typed((row[0], row[1]))["channel_values"]
    if context["role"] != "admin" and saved.get("group") != context.get("group"):
        raise PermissionError("legacy usage review requires the task's group")
    owner = {field: saved.get(field) for field in ("actor_id", "group", "role", "workspace_id", "workspace_path", "resource_scopes")}
    return legacy_checkpoint_binding({**context, **owner}, thread_id=thread_id, db_path=database)


def read_usage(request: UsageRead, context: dict, database: Path) -> dict:
    binding = _binding(context, database, request.thread_id)
    summary = usage_state(database, request.thread_id, binding["owner_digest"])
    path = _ledger(database)
    if path.exists():
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
            rows = _requests(conn, request.thread_id, binding["owner_digest"])
            reviews = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM legacy_usage_reviews WHERE thread_id=? ORDER BY reviewed_at,review_id", (request.thread_id,))] \
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_usage_reviews'").fetchone() else []
    else:
        rows, reviews = [], []
    if _binding(context, database, request.thread_id) != binding:
        raise ValueError("legacy checkpoint changed during usage preview")
    result = {"engine": "legacy-python", "thread_id": request.thread_id, "checkpoint_id": binding["checkpoint_id"],
              "checkpoint_digest": binding["checkpoint_digest"], "usage": summary, "requests": rows,
              "reviews": reviews, "execution_started": False}
    if context["role"] == "admin":
        from runner.admin_scope import audited_read_result
        return audited_read_result("legacy_usage.read", {**context, "evidence_dir": database.parent / "evidence"}, result)
    return result


def review_usage(request: UsageReview, context: dict, database: Path, reauthorize) -> dict:
    # Same lock as original Runner: a live request cannot race human settlement.
    with execution_lock(database, request.thread_id):
        binding = _binding(context, database, request.thread_id)
        if binding["checkpoint_id"] != request.checkpoint_id or binding["checkpoint_digest"] != request.checkpoint_digest:
            raise ValueError("legacy checkpoint changed; reload usage before review")
        path = _ledger(database)
        if not path.is_file():
            raise ValueError("legacy model request not found")
        usage_state(database, request.thread_id, binding["owner_digest"])
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            original = next((row for row in _requests(conn, request.thread_id, binding["owner_digest"]) if row["request_id"] == request.request_id), None)
            if not original or original["reservation_digest"] != request.expected_digest or original["status"] != "unconfirmed":
                raise ValueError("model reservation changed, was settled or is unavailable")
            receipt = request.receipt.model_dump() if request.receipt else {"input_tokens": 0, "output_tokens": 0, "tokens": 0, "cost": 0}
            audit = {**request.model_dump(exclude={"receipt"}), **receipt, "owner_digest": binding["owner_digest"],
                     "reviewer": context["actor_id"], "reviewer_session": context["session_id"],
                     "reviewed_at": datetime.now(timezone.utc).isoformat(), "review_id": uuid4().hex}
            reauthorize()
            append_event(request.thread_id, "output_data", {"legacy_usage_review_intent": audit}, database.parent / "evidence", required=True)
            conn.execute("CREATE TABLE IF NOT EXISTS legacy_usage_reviews (review_id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,reviewed_at TEXT NOT NULL,payload TEXT NOT NULL,original_reservation TEXT NOT NULL)")
            conn.execute("INSERT INTO legacy_usage_reviews VALUES(?,?,?,?,?)", (audit["review_id"], request.thread_id, audit["reviewed_at"], json.dumps(audit), json.dumps(original)))
            changed = conn.execute("UPDATE legacy_model_usage SET input=?,output=?,total=?,cost=? WHERE request_id=? AND thread_id=? AND total IS NULL",
                                   (receipt["input_tokens"], receipt["output_tokens"], receipt["tokens"], receipt["cost"], request.request_id, request.thread_id))
            if changed.rowcount != 1:
                raise ValueError("legacy reservation changed during review")
        return {"review": audit, "usage": usage_state(database, request.thread_id, binding["owner_digest"]), "execution_started": False}
