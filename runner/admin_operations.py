"""Durable deployment management, deliberately outside the Agent Tool Catalog."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from schemas.admin_deploy import AdminDeployRequest, AdminDeployResult, AdminDeployStatus
from runner.langgraph_base import PROJECT_ROOT


def _connection(database: Path | None):
    path = database or PROJECT_ROOT / ".quantcode" / "deployments.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS deployments ("
                 "deployment_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, request_id TEXT NOT NULL, "
                 "record_hash TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, "
                 "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(actor_id,request_id))")
    return conn


def _authorize(role: str, actor: str):
    if role != "admin" or not actor:
        raise PermissionError("authenticated Admin required")


def submit_deploy(request: AdminDeployRequest, *, session_role: str, actor_id: str = "",
                  evidence_dir: str | Path | None = None, database: Path | None = None) -> AdminDeployResult:
    """Admit a durable, idempotent staging record, never pretend to execute it."""
    _authorize(session_role, actor_id)
    payload = request.model_dump(mode="json", exclude={"request_id"})
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    request_id = request.request_id or digest
    deployment_id = hashlib.sha256(f"{actor_id}:{request_id}".encode()).hexdigest()
    conn = _connection(database)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)).fetchone()
            if existing:
                if existing["record_hash"] != digest:
                    raise ValueError("idempotency conflict: request_id was used with different content")
                return AdminDeployResult(status=existing["status"], artifact_ref=request.artifact_ref,
                                         record_hash=digest, deployment_id=deployment_id)
            from runner.evidence import EVIDENCE_DIR, append_event
            append_event(f"admin-deploy-{deployment_id}", "output_data", {
                "actor_id": actor_id, "artifact_ref": request.artifact_ref, "target": request.target,
                "status": "STAGING", "record_hash": digest, "request_id": request_id,
            }, evidence_dir or EVIDENCE_DIR, required=True)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("INSERT INTO deployments VALUES(?,?,?,?,?,?,?,?)", (
                deployment_id, actor_id, request_id, digest, serialized, "STAGING", now, now,
            ))
    finally:
        conn.close()
    return AdminDeployResult(status=AdminDeployStatus.STAGING, artifact_ref=request.artifact_ref,
                             record_hash=digest, deployment_id=deployment_id)


def list_deployments(*, session_role: str, actor_id: str, database: Path | None = None,
                     evidence_dir: str | Path | None = None, limit: int = 100) -> dict:
    _authorize(session_role, actor_id)
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    conn = _connection(database)
    try:
        rows = conn.execute("SELECT * FROM deployments ORDER BY created_at DESC, deployment_id DESC LIMIT ?", (limit,)).fetchall()
        result = {"deployments": [{**dict(row), "payload": json.loads(row["payload"])} for row in rows],
                  "executor_status": "UNAVAILABLE", "executor_message": "Production executor is not configured"}
        from runner.admin_scope import audited_read_result
        return audited_read_result("admin_deployments", {"actor_id": actor_id, "role": session_role, "evidence_dir": evidence_dir}, result)
    finally:
        conn.close()


def cancel_deployment(deployment_id: str, *, session_role: str, actor_id: str,
                      database: Path | None = None, evidence_dir: str | Path | None = None) -> dict:
    _authorize(session_role, actor_id)
    conn = _connection(database)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)).fetchone()
            if row is None:
                raise KeyError("deployment not found")
            if row["status"] == "CANCELLED":
                return {"deployment_id": deployment_id, "status": "CANCELLED"}
            if row["status"] != "STAGING":
                raise ValueError("only a staged request can be cancelled")
            from runner.evidence import EVIDENCE_DIR, append_event
            append_event(f"admin-deploy-{deployment_id}", "output_data", {
                "actor_id": actor_id, "status": "CANCELLED", "record_hash": row["record_hash"],
            }, evidence_dir or EVIDENCE_DIR, required=True)
            conn.execute("UPDATE deployments SET status='CANCELLED', updated_at=? WHERE deployment_id=?", (
                datetime.now(timezone.utc).isoformat(), deployment_id))
            return {"deployment_id": deployment_id, "status": "CANCELLED"}
    finally:
        conn.close()


__all__ = ["submit_deploy", "list_deployments", "cancel_deployment"]
