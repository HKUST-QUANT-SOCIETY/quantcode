"""Gateway-owned GitHub polling for currently authenticated identities.

No bearer tokens are recovered or copied. Every scheduled identity is resolved
against the live session table and roster before using the regular GitHub ACL.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _key(context: dict) -> str:
    fields = ("actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject")
    return hashlib.sha256(json.dumps([
        *[context.get(field) for field in fields], sorted(context.get("resource_scopes") or []),
    ]).encode()).hexdigest()


def _save(database: Path, context: dict, result: dict) -> None:
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS github_sync_status (scope TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("INSERT INTO github_sync_status VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET payload=excluded.payload",
                     (_key(context), json.dumps(result)))


def read_status(database: Path, context: dict) -> dict:
    with sqlite3.connect(database) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='github_sync_status'").fetchone()
        if not exists:
            return {"last_attempt_status": "NOT_OBSERVED"}
        row = conn.execute("SELECT payload FROM github_sync_status WHERE scope=?", (_key(context),)).fetchone()
        return json.loads(row[0]) if row else {"last_attempt_status": "NOT_OBSERVED"}


def sync_once(gateway, *, sync=None, stop=None) -> None:
    if sync is None:
        from runner.github_sync import sync_graph
        sync = sync_graph
    with sqlite3.connect(gateway.database) as conn:
        digests = [row[0] for row in conn.execute("SELECT token_hash FROM identity_sessions")]
    observed = set()
    for digest in digests:
        if stop is not None and stop.is_set():
            return
        try:
            context = gateway.session_digest(digest).model_dump(mode="json")
        except PermissionError:
            continue
        key = _key(context)
        if key in observed:
            continue
        observed.add(key)
        attempt = {"started_at": datetime.now(timezone.utc).isoformat(), "last_attempt_status": "STARTED"}
        _save(gateway.database, context, attempt)
        try:
            result = sync(context)
            attempt.update(last_attempt_status=result["sync_status"], repositories=len(result.get("repos", [])))
        except Exception as exc:
            # Raw transport exceptions can contain request credentials. Persist
            # only the class; detailed repo errors remain in the scoped graph API.
            attempt.update(last_attempt_status="ERROR", error_type=type(exc).__name__)
        attempt["finished_at"] = datetime.now(timezone.utc).isoformat()
        _save(gateway.database, context, attempt)


def serve(gateway, stop, interval: int) -> None:
    while not stop.is_set():
        try:
            sync_once(gateway, stop=stop)
        except Exception as exc:
            logging.getLogger(__name__).error("GitHub sync cycle failed (%s)", type(exc).__name__)
        stop.wait(interval)
