"""Host-only archival of pre-manifest native task projections.

This copies exact original gateway rows within the existing SQLite database.
It does not reconstruct artifacts, issue task events or run an executor.
Only an authenticated native publisher can later supply an actual new snapshot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from schemas.evidence_chain import canonical_json, sha256_hex

FIELDS = (
    "source_id", "session_id", "root_session_id", "parent_session_id", "owner_actor", "owner_group",
    "owner_workspace", "owner_json", "source_revision", "record_digest", "task_json", "received_at",
)


class NativeTaskMigrationRequired(ValueError):
    """An authorized caller reached a historical projection pending rebuild."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS native_task_legacy_archive ("
                 "source_id TEXT NOT NULL, session_id TEXT NOT NULL, original_row_json TEXT NOT NULL, "
                 "archive_digest TEXT NOT NULL, archived_at TEXT NOT NULL, "
                 "PRIMARY KEY(source_id,session_id))")
    # All service code treats this as an archive, never a replaceable cache.
    conn.execute("CREATE TRIGGER IF NOT EXISTS native_task_legacy_archive_no_update "
                 "BEFORE UPDATE ON native_task_legacy_archive BEGIN "
                 "SELECT RAISE(ABORT,'native task archive is immutable'); END")
    conn.execute("CREATE TRIGGER IF NOT EXISTS native_task_legacy_archive_no_delete "
                 "BEFORE DELETE ON native_task_legacy_archive BEGIN "
                 "SELECT RAISE(ABORT,'native task archive is immutable'); END")
    conn.execute("CREATE TABLE IF NOT EXISTS native_task_legacy_rebuilds ("
                 "source_id TEXT NOT NULL, session_id TEXT NOT NULL, source_revision INTEGER NOT NULL, "
                 "record_digest TEXT NOT NULL, updated_at INTEGER NOT NULL, "
                 "PRIMARY KEY(source_id,session_id,source_revision))")
    conn.execute("CREATE TRIGGER IF NOT EXISTS native_task_legacy_rebuilds_no_update "
                 "BEFORE UPDATE ON native_task_legacy_rebuilds BEGIN "
                 "SELECT RAISE(ABORT,'native task rebuild receipt is immutable'); END")
    conn.execute("CREATE TRIGGER IF NOT EXISTS native_task_legacy_rebuilds_no_delete "
                 "BEFORE DELETE ON native_task_legacy_rebuilds BEGIN "
                 "SELECT RAISE(ABORT,'native task rebuild receipt is immutable'); END")


def legacy(row: sqlite3.Row | dict) -> bool:
    task = json.loads(row["task_json"])
    return isinstance(task, dict) and "artifact_manifest_hash" not in task


def record(row: sqlite3.Row | dict) -> tuple[dict, dict]:
    """Validate original digest/lineage without inventing new-schema fields."""
    task, owner = json.loads(row["task_json"]), json.loads(row["owner_json"])
    required_owner = {"actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject", "resource_scopes"}
    if not isinstance(task, dict) or not isinstance(owner, dict) or set(owner) != required_owner:
        raise ValueError("legacy task owner record is invalid")
    if not isinstance(owner["resource_scopes"], list) or not all(isinstance(scope, str) for scope in owner["resource_scopes"]):
        raise ValueError("legacy task scopes are invalid")
    if (owner["actor_id"], owner["group"], owner["workspace_id"]) != (row["owner_actor"], row["owner_group"], row["owner_workspace"]):
        raise ValueError("legacy task owner columns disagree")
    if sha256_hex(canonical_json({"owner": owner, "task": task})) != row["record_digest"]:
        raise ValueError("legacy task original record digest mismatch")
    if (task.get("source_id"), task.get("session_id"), task.get("root_session_id"), task.get("parent_session_id"), task.get("source_revision")) != (
        row["source_id"], row["session_id"], row["root_session_id"], row["parent_session_id"], row["source_revision"],
    ):
        raise ValueError("legacy task lineage columns disagree")
    if any(type(task.get(field)) is not int or task[field] < 0 for field in ("source_revision", "created_at", "updated_at")):
        raise ValueError("legacy task version or timestamps are invalid")
    if task["updated_at"] < task["created_at"] or not isinstance(task.get("title"), str):
        raise ValueError("legacy task timestamps or title are invalid")
    if (task["root_session_id"] == task["session_id"]) != (task.get("parent_session_id") is None):
        raise ValueError("legacy task root relationship is invalid")
    return task, owner


def archived(conn: sqlite3.Connection, source_id: str, session_id: str) -> dict | None:
    item = conn.execute("SELECT * FROM native_task_legacy_archive WHERE source_id=? AND session_id=?", (source_id, session_id)).fetchone()
    if item is None:
        return None
    if sha256_hex(item["original_row_json"]) != item["archive_digest"]:
        raise ValueError("native task legacy archive digest mismatch")
    original = json.loads(item["original_row_json"])
    if not isinstance(original, dict) or set(original) != set(FIELDS) or (original["source_id"], original["session_id"]) != (source_id, session_id):
        raise ValueError("native task legacy archive identity mismatch")
    if not legacy(original):
        raise ValueError("native task archive is not a pre-manifest record")
    record(original)
    return original


def records_sql() -> str:
    """Include archived owner reservations if the rebuildable live cache is gone."""
    fields = ",".join(FIELDS)
    archived_fields = ",".join(f"json_extract(a.original_row_json,'$.{field}') AS {field}" for field in FIELDS)
    return f"WITH native_task_records AS (SELECT {fields} FROM native_tasks UNION ALL SELECT {archived_fields} " \
           "FROM native_task_legacy_archive a WHERE NOT EXISTS (SELECT 1 FROM native_tasks n " \
           "WHERE n.source_id=a.source_id AND n.session_id=a.session_id)) "


def pending(conn: sqlite3.Connection, row: sqlite3.Row | dict) -> dict:
    task, _ = record(row)
    original = archived(conn, row["source_id"], row["session_id"])
    if original is not None and canonical_json(dict(row)) != canonical_json(original):
        raise ValueError("legacy task changed after archival")
    return {"source_id": task["source_id"], "session_id": task["session_id"],
            "root_session_id": task["root_session_id"], "source_revision": task["source_revision"],
            "title": task["title"], "state": "awaiting_rebuild" if original else "awaiting_archive",
            "message": "历史任务正在等待恢复索引，可稍后刷新或联系维护者查看原始记录。"}


def receipt(conn: sqlite3.Connection, task: dict, digest: str) -> None:
    """Monotone publication receipt survives deletion of the live projection.

    It carries no execution status or tool data; the native event source still
    owns task facts. The receipt only prevents replaying an older rebuilt page.
    """
    last = conn.execute("SELECT * FROM native_task_legacy_rebuilds WHERE source_id=? AND session_id=? "
                        "ORDER BY source_revision DESC LIMIT 1", (task["source_id"], task["session_id"])).fetchone()
    if last:
        if task["source_revision"] < last["source_revision"] or task["updated_at"] < last["updated_at"]:
            raise ValueError("rebuilt native task projection revision regressed")
        if task["source_revision"] == last["source_revision"] and digest != last["record_digest"]:
            raise ValueError("rebuilt native task projection retry conflicts")
    conn.execute("INSERT OR IGNORE INTO native_task_legacy_rebuilds VALUES(?,?,?,?,?)", (
        task["source_id"], task["session_id"], task["source_revision"], digest, task["updated_at"],
    ))


def _snapshot(conn: sqlite3.Connection) -> dict:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_tasks'").fetchone():
        return {"version": 1, "rows": []}
    has_archive = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_task_legacy_archive'").fetchone())
    rows = []
    for row in conn.execute("SELECT * FROM native_tasks ORDER BY source_id,session_id"):
        if not legacy(row):
            continue
        record(row)
        original = archived(conn, row["source_id"], row["session_id"]) if has_archive else None
        if original is not None and canonical_json(original) != canonical_json(dict(row)):
            raise ValueError("legacy task changed after archival")
        rows.append({"original": dict(row), "archived": original is not None})
    return {"version": 1, "rows": rows}


def _database(path: Path, *, writable: bool) -> sqlite3.Connection:
    if not path.is_absolute() or path.resolve() != path or os.name != "posix":
        raise PermissionError("migration requires an existing canonical host-private gateway database")
    info = path.stat()
    parent = path.parent.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise PermissionError("gateway database and parent must be private and owned by this host account")
    conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def preflight(path: Path) -> dict:
    conn = _database(path, writable=False)
    try:
        conn.execute("BEGIN")
        snapshot = _snapshot(conn)
        return {"action": "preflight", "expected_digest": sha256_hex(canonical_json(snapshot)),
                "records": [{"source_id": entry["original"]["source_id"], "session_id": entry["original"]["session_id"],
                             "source_revision": entry["original"]["source_revision"],
                             "original_record_digest": entry["original"]["record_digest"], "archived": entry["archived"]}
                            for entry in snapshot["rows"]],
                "effect": "archive exact original rows; no task/artifact conversion or execution"}
    finally:
        conn.close()


def archive(path: Path, expected_digest: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise ValueError("archive requires the exact preflight digest")
    conn = _database(path, writable=True)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = _snapshot(conn)
            if sha256_hex(canonical_json(snapshot)) != expected_digest:
                raise ValueError("migration preflight changed; review a fresh preflight")
            ensure_schema(conn)
            count = 0
            for entry in snapshot["rows"]:
                if entry["archived"]:
                    continue
                original = entry["original"]
                encoded = canonical_json(original)
                conn.execute("INSERT INTO native_task_legacy_archive VALUES(?,?,?,?,?)", (
                    original["source_id"], original["session_id"], encoded, sha256_hex(encoded),
                    datetime.now(timezone.utc).isoformat(),
                ))
                count += 1
            return {"action": "archive", "preflight_digest": expected_digest, "archived": count,
                    "execution": "none", "next": "native publisher rebuilds from actual EventTable under original owner"}
    finally:
        conn.close()


def read_archive(path: Path, source_id: str, session_id: str) -> dict:
    conn = _database(path, writable=False)
    try:
        conn.execute("BEGIN")
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_task_legacy_archive'").fetchone():
            raise KeyError("legacy archive has not been created; run preflight")
        original = archived(conn, source_id, session_id)
        if original is None:
            raise KeyError("legacy archive not found")
        return {"format": "legacy-inline-artifacts", "read_only": True,
                "archive_digest": sha256_hex(canonical_json(original)), "original": original,
                "notice": "historical projection only; artifact contents have no invented native provenance"}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("preflight")
    execute = sub.add_parser("archive")
    execute.add_argument("--expected-digest", required=True)
    read = sub.add_parser("read")
    read.add_argument("--source-id", required=True)
    read.add_argument("--session-id", required=True)
    args = parser.parse_args()
    if args.action == "preflight":
        result = preflight(args.database)
    elif args.action == "archive":
        result = archive(args.database, args.expected_digest)
    else:
        result = read_archive(args.database, args.source_id, args.session_id)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
