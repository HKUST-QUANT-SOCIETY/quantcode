"""Authorized organization index of native EventTable summaries.

The gateway accepts monotonically versioned descriptions from authenticated
hosts. It never advances a task, runs tools, forwards to host URLs, or cancels a
runner. ``received_at`` records index delivery, not execution liveness.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import TYPE_CHECKING

from schemas.evidence_chain import canonical_json, sha256_hex
from schemas.native_tasks import (
    CHUNK_BYTES, NativeArtifact, NativeArtifactList, NativeArtifactPublish, NativeArtifactRead,
    NativeTaskList, NativeTaskPublish, NativeTaskRead, NativeTaskSummary,
)
from schemas.session_context import SessionContext
from quantcode import native_task_migration

if TYPE_CHECKING:
    from quantcode.gateway import IdentityGateway


def _now() -> int:
    return (datetime.now(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1)


def _connection(gateway: IdentityGateway) -> sqlite3.Connection:
    conn = sqlite3.connect(gateway.database, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS native_tasks ("
                 "source_id TEXT NOT NULL, session_id TEXT NOT NULL, root_session_id TEXT NOT NULL, "
                 "parent_session_id TEXT, owner_actor TEXT NOT NULL, owner_group TEXT NOT NULL, "
                 "owner_workspace TEXT NOT NULL, owner_json TEXT NOT NULL, source_revision INTEGER NOT NULL, "
                 "record_digest TEXT NOT NULL, task_json TEXT NOT NULL, received_at INTEGER NOT NULL, "
                 "PRIMARY KEY(source_id,session_id))")
    conn.execute("CREATE INDEX IF NOT EXISTS native_tasks_principal "
                 "ON native_tasks(owner_actor,owner_group,owner_workspace)")
    conn.execute("CREATE INDEX IF NOT EXISTS native_tasks_parent "
                 "ON native_tasks(source_id,parent_session_id)")
    conn.execute("CREATE TABLE IF NOT EXISTS native_task_artifacts ("
                 "source_id TEXT NOT NULL, session_id TEXT NOT NULL, artifact_id TEXT NOT NULL, "
                 "artifact_json TEXT NOT NULL, artifact_digest TEXT NOT NULL, content_complete INTEGER NOT NULL DEFAULT 0, "
                 "PRIMARY KEY(source_id,session_id,artifact_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS native_task_artifact_versions ("
                 "source_id TEXT NOT NULL, session_id TEXT NOT NULL, source_revision INTEGER NOT NULL, artifact_id TEXT NOT NULL, "
                 "PRIMARY KEY(source_id,session_id,source_revision,artifact_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS native_task_artifact_chunks ("
                 "source_id TEXT NOT NULL, session_id TEXT NOT NULL, artifact_id TEXT NOT NULL, "
                 "offset INTEGER NOT NULL, chunk BLOB NOT NULL, chunk_sha256 TEXT NOT NULL, "
                 "PRIMARY KEY(source_id,session_id,artifact_id,offset))")
    native_task_migration.ensure_schema(conn)
    return conn


def _session(gateway: IdentityGateway, token: str, expected: str) -> SessionContext:
    context = gateway.session(token)
    if context.session_id != expected:
        raise PermissionError("session changed; reconnect before reading task history")
    return context


def _owner(context: SessionContext) -> dict:
    # Login expiry is not task ownership. A renewed roster session may publish
    # the same source record only while its original principal grants match.
    return {**{field: getattr(context, field) for field in (
        "actor_id", "group", "role", "workspace_id", "workspace_path", "github_subject")},
        "resource_scopes": sorted(set(context.resource_scopes))}


def _authorize(context: SessionContext, row: sqlite3.Row) -> None:
    if context.role == "admin":
        return
    # A renewed login is not allowed to inherit a historical projection after
    # its role, scopes, workspace path, or GitHub subject changed. Compare the
    # complete original principal snapshot, not only its display tuple.
    if canonical_json(_owner(context)) != row["owner_json"]:
        raise PermissionError("current roster identity cannot read this task")


def _stored_task(row: sqlite3.Row) -> tuple[dict, dict]:
    owner = json.loads(row["owner_json"])
    task = NativeTaskSummary.model_validate_json(row["task_json"]).model_dump(mode="json", exclude_none=True)
    # Cost null is meaningful even when optional descriptive fields are absent.
    task["cost"] = json.loads(row["task_json"])["cost"]
    if sha256_hex(canonical_json({"owner": owner, "task": task})) != row["record_digest"]:
        raise ValueError("native task index digest mismatch")
    if (task["source_id"], task["session_id"], task["root_session_id"], task.get("parent_session_id"), task["source_revision"]) != (
        row["source_id"], row["session_id"], row["root_session_id"], row["parent_session_id"], row["source_revision"]
    ) or (owner["actor_id"], owner["group"], owner["workspace_id"]) != (
        row["owner_actor"], row["owner_group"], row["owner_workspace"]
    ):
        raise ValueError("native task index ownership mismatch")
    return task, owner


def _summary(row: sqlite3.Row) -> dict:
    task, owner = _stored_task(row)
    return {**task, **{field: owner[field] for field in ("actor_id", "group", "role", "workspace_id")},
            "received_at": row["received_at"]}


def _artifact(row: sqlite3.Row) -> dict:
    artifact = NativeArtifact.model_validate_json(row["artifact_json"]).model_dump(mode="json", exclude_none=True)
    if sha256_hex(canonical_json(artifact)) != row["artifact_digest"] or artifact["id"] != row["artifact_id"]:
        raise ValueError("artifact reference digest mismatch")
    return artifact


def _artifact_ref(conn: sqlite3.Connection, task: dict, value: NativeArtifact) -> None:
    if value.source_event_seq > task["source_revision"]:
        raise ValueError("artifact event follows the published task revision")
    artifact = value.model_dump(mode="json", exclude_none=True)
    encoded = canonical_json(artifact)
    key = (task["source_id"], task["session_id"], value.id)
    previous = conn.execute("SELECT * FROM native_task_artifacts WHERE source_id=? AND session_id=? AND artifact_id=?", key).fetchone()
    if previous:
        if _artifact(previous) != artifact:
            raise ValueError("artifact identity has conflicting immutable content")
    else:
        conn.execute("INSERT INTO native_task_artifacts VALUES(?,?,?,?,?,0)", (*key, encoded, sha256_hex(encoded)))
    conn.execute("INSERT OR IGNORE INTO native_task_artifact_versions VALUES(?,?,?,?)", (
        task["source_id"], task["session_id"], task["source_revision"], value.id,
    ))


def _manifest(conn: sqlite3.Connection, task: dict) -> bool:
    records = conn.execute("SELECT a.* FROM native_task_artifact_versions v JOIN native_task_artifacts a "
                           "ON a.source_id=v.source_id AND a.session_id=v.session_id AND a.artifact_id=v.artifact_id "
                           "WHERE v.source_id=? AND v.session_id=? AND v.source_revision=? ORDER BY a.artifact_id", (
                               task["source_id"], task["session_id"], task["source_revision"],
                           )).fetchall()
    if len(records) > task["artifact_count"]:
        raise ValueError("artifact manifest exceeds the published count")
    if len(records) < task["artifact_count"]:
        return False
    if sha256_hex(canonical_json([_artifact(row) for row in records])) != task["artifact_manifest_hash"]:
        raise ValueError("artifact manifest digest mismatch")
    return True


def _artifact_status(row: sqlite3.Row, complete: bool) -> dict:
    ref = _artifact(row)
    status = "unavailable" if ref["capture_status"] == "unavailable" else "available" if complete and row["content_complete"] else "pending"
    return {**ref, "delivery_status": status}


def _artifact_page(conn: sqlite3.Connection, task: dict, *, limit: int = 32, cursor: str | None = None) -> dict:
    scope = [task["source_id"], task["session_id"], task["source_revision"], task["artifact_manifest_hash"]]
    after = ""
    if cursor:
        try:
            decoded = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if not isinstance(decoded, list) or len(decoded) != 2 or decoded[0] != scope or not isinstance(decoded[1], str):
                raise ValueError("invalid cursor")
            after = decoded[1]
        except (ValueError, TypeError, UnicodeError) as error:
            raise ValueError("artifact cursor does not match the authorized task version") from error
    complete = _manifest(conn, task)
    rows = conn.execute("SELECT a.* FROM native_task_artifact_versions v JOIN native_task_artifacts a "
                        "ON a.source_id=v.source_id AND a.session_id=v.session_id AND a.artifact_id=v.artifact_id "
                        "WHERE v.source_id=? AND v.session_id=? AND v.source_revision=? AND a.artifact_id>? "
                        "ORDER BY a.artifact_id LIMIT ?", (
                            task["source_id"], task["session_id"], task["source_revision"], after, limit + 1,
                        )).fetchall()
    next_cursor = base64.urlsafe_b64encode(canonical_json([scope, rows[limit - 1]["artifact_id"]]).encode()).decode() if len(rows) > limit else None
    return {"source_revision": task["source_revision"], "artifact_manifest_hash": task["artifact_manifest_hash"],
            "artifact_count": task["artifact_count"], "artifacts": [_artifact_status(row, complete) for row in rows[:limit]],
            "next_cursor": next_cursor, "manifest_complete": complete}


def _audit(gateway: IdentityGateway, context: SessionContext, operation: str, result: dict) -> dict:
    if context.role != "admin":
        return result
    from runner.admin_scope import audited_read_result

    return audited_read_result(operation, {
        **context.model_dump(mode="json"), "evidence_dir": str(gateway.database.parent / "evidence"),
    }, result)


def publish(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeTaskPublish.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    owner = _owner(context)
    serialized_owner = canonical_json(owner)
    task = value.task.model_dump(mode="json", exclude_none=True)
    task["cost"] = value.task.cost
    digest = sha256_hex(canonical_json({"owner": owner, "task": task}))
    conn = _connection(gateway)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT * FROM native_tasks WHERE source_id=? AND session_id=?", (
                value.task.source_id, value.task.session_id,
            )).fetchone()
            original = native_task_migration.archived(conn, value.task.source_id, value.task.session_id)
            if original:
                archived_task, _ = native_task_migration.record(original)
                if original["owner_json"] != serialized_owner:
                    raise PermissionError("archived task publisher or original authorization changed")
                if (value.task.root_session_id, value.task.parent_session_id, value.task.created_at) != (
                    archived_task["root_session_id"], archived_task.get("parent_session_id"), archived_task["created_at"],
                ):
                    raise ValueError("archived native task ownership and lineage are immutable")
                if value.task.source_revision < original["source_revision"] or value.task.updated_at < archived_task["updated_at"]:
                    raise ValueError("archived native task projection revision regressed")
                native_task_migration.receipt(conn, task, digest)
            if previous:
                if previous["owner_json"] != serialized_owner:
                    raise PermissionError("task publisher or its original authorization changed")
                legacy = native_task_migration.legacy(previous)
                if legacy and original is None:
                    raise native_task_migration.NativeTaskMigrationRequired("legacy projection requires exact host archival before rebuild")
                if legacy and canonical_json(dict(previous)) != canonical_json(original):
                    raise ValueError("legacy native task changed after archival")
                before = native_task_migration.record(previous)[0] if legacy else _summary(previous)
                if (value.task.root_session_id, value.task.parent_session_id, value.task.created_at) != (
                    before["root_session_id"], before.get("parent_session_id"), before["created_at"]
                ):
                    raise ValueError("native task ownership and lineage are immutable")
                if value.task.source_revision < previous["source_revision"] or value.task.updated_at < before["updated_at"]:
                    raise ValueError("native task projection revision regressed")
                if not legacy and value.task.source_revision == previous["source_revision"] and digest != previous["record_digest"]:
                    raise ValueError("native task revision has conflicting content")
            related = conn.execute(native_task_migration.records_sql() + "SELECT * FROM native_task_records WHERE source_id=? AND "
                                   "(session_id IN (?,?) OR parent_session_id=? OR root_session_id=?)", (
                                       value.task.source_id, value.task.root_session_id, value.task.parent_session_id,
                                       value.task.session_id, value.task.session_id,
                                   )).fetchall()
            for relative in related:
                if native_task_migration.legacy(relative):
                    native_task_migration.pending(conn, relative)
                    record = native_task_migration.record(relative)[0]
                else:
                    record = _summary(relative)
                if relative["owner_json"] != serialized_owner or record["root_session_id"] != value.task.root_session_id:
                    raise PermissionError("native task ancestry belongs to a different owner or root")
            # Check existing ancestry without requiring parent-first delivery.
            # An absent parent is a lagging projection, never an execution grant.
            parent = value.task.parent_session_id
            seen = {value.task.session_id}
            while parent:
                if parent in seen:
                    raise ValueError("native task projection contains a parent cycle")
                seen.add(parent)
                ancestor = conn.execute(native_task_migration.records_sql() + "SELECT parent_session_id FROM native_task_records WHERE source_id=? AND session_id=?", (
                    value.task.source_id, parent,
                )).fetchone()
                parent = ancestor["parent_session_id"] if ancestor else None
            conn.execute("INSERT INTO native_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                         "ON CONFLICT(source_id,session_id) DO UPDATE SET source_revision=excluded.source_revision, "
                         "record_digest=excluded.record_digest, task_json=excluded.task_json, received_at=excluded.received_at", (
                             value.task.source_id, value.task.session_id, value.task.root_session_id, value.task.parent_session_id,
                             context.actor_id, context.group, context.workspace_id, serialized_owner,
                             value.task.source_revision, digest, canonical_json(task), _now(),
                         ))
            for artifact in value.task.artifacts:
                _artifact_ref(conn, task, artifact)
            _manifest(conn, task)
        # A revoked publisher must not receive a successful authorization claim.
        # Its already delivered history remains an immutable-principal projection.
        _session(gateway, token, value.expected_session_id)
        row = conn.execute(native_task_migration.records_sql() + "SELECT * FROM native_task_records WHERE source_id=? AND session_id=?", (
            value.task.source_id, value.task.session_id,
        )).fetchone()
        return {"task": _summary(row)}
    finally:
        conn.close()


def read(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeTaskRead.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    conn = _connection(gateway)
    try:
        conn.execute("BEGIN")
        row = conn.execute(native_task_migration.records_sql() + "SELECT * FROM native_task_records WHERE source_id=? AND session_id=?", (
            value.source_id, value.session_id,
        )).fetchone()
        if row is None:
            raise KeyError("native task not found")
        _authorize(context, row)
        if native_task_migration.legacy(row):
            native_task_migration.pending(conn, row)
            _audit(gateway, context, "native_tasks.legacy_pending", {"source_id": value.source_id, "session_id": value.session_id})
            _session(gateway, token, value.expected_session_id)
            raise native_task_migration.NativeTaskMigrationRequired("historical task index awaits a native source rebuild")
        task = _summary(row)
        page = _artifact_page(conn, task)
    finally:
        conn.close()
    result = _audit(gateway, context, "native_tasks.read", {
        "task": task,
        "artifacts": page["artifacts"],
        "artifacts_next_cursor": page["next_cursor"],
    })
    _session(gateway, token, value.expected_session_id)
    return result


def _artifact_task(conn: sqlite3.Connection, context: SessionContext, value: NativeArtifactRead | NativeArtifactList | NativeArtifactPublish) -> dict:
    row = conn.execute(native_task_migration.records_sql() + "SELECT * FROM native_task_records WHERE source_id=? AND session_id=?", (
        value.source_id, value.session_id,
    )).fetchone()
    if row is None:
        raise KeyError("native task not found")
    _authorize(context, row)
    if native_task_migration.legacy(row):
        native_task_migration.pending(conn, row)
        raise native_task_migration.NativeTaskMigrationRequired("historical artifact index awaits a native source rebuild")
    task = _summary(row)
    if value.source_revision != task["source_revision"]:
        raise ValueError("artifact task version changed; reload the task")
    return task


def publish_artifact(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeArtifactPublish.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    conn = _connection(gateway)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            task = _artifact_task(conn, context, value)
            # Admin read access is never authority to publish somebody else's
            # results. Only the complete original principal may supply bytes.
            owner = conn.execute("SELECT owner_json FROM native_tasks WHERE source_id=? AND session_id=?", (
                value.source_id, value.session_id,
            )).fetchone()
            if owner["owner_json"] != canonical_json(_owner(context)):
                raise PermissionError("artifact publisher differs from the task owner")
            _artifact_ref(conn, task, value.artifact)
            key = (value.source_id, value.session_id, value.artifact.id)
            if value.content is not None:
                data = base64.b64decode(value.content, validate=True)
                previous = conn.execute("SELECT chunk,chunk_sha256 FROM native_task_artifact_chunks "
                                        "WHERE source_id=? AND session_id=? AND artifact_id=? AND offset=?", (*key, value.offset)).fetchone()
                if previous and (previous["chunk"] != data or previous["chunk_sha256"] != value.chunk_sha256):
                    raise ValueError("artifact chunk retry conflicts with original bytes")
                conn.execute("INSERT OR IGNORE INTO native_task_artifact_chunks VALUES(?,?,?,?,?,?)", (
                    *key, value.offset, data, value.chunk_sha256,
                ))
                count = conn.execute("SELECT COUNT(*) AS count,SUM(length(chunk)) AS size FROM native_task_artifact_chunks "
                                     "WHERE source_id=? AND session_id=? AND artifact_id=?", key).fetchone()
                expected_chunks = max(1, (value.artifact.bytes + CHUNK_BYTES - 1) // CHUNK_BYTES)
                if count["count"] > expected_chunks or count["size"] > value.artifact.bytes:
                    raise ValueError("artifact chunks exceed original byte length")
                if count["count"] == expected_chunks:
                    digest = hashlib.sha256()
                    offset = 0
                    for chunk in conn.execute("SELECT offset,chunk,chunk_sha256 FROM native_task_artifact_chunks "
                                              "WHERE source_id=? AND session_id=? AND artifact_id=? ORDER BY offset", key):
                        if chunk["offset"] != offset or hashlib.sha256(chunk["chunk"]).hexdigest() != chunk["chunk_sha256"]:
                            raise ValueError("artifact chunk sequence or digest mismatch")
                        digest.update(chunk["chunk"])
                        offset += len(chunk["chunk"])
                    if offset != value.artifact.bytes or digest.hexdigest() != value.artifact.sha256:
                        raise ValueError("artifact original content digest mismatch")
                    conn.execute("UPDATE native_task_artifacts SET content_complete=1 "
                                 "WHERE source_id=? AND session_id=? AND artifact_id=?", key)
            complete = _manifest(conn, task)
            row = conn.execute("SELECT * FROM native_task_artifacts WHERE source_id=? AND session_id=? AND artifact_id=?", key).fetchone()
            result = {"source_revision": value.source_revision, "artifact": _artifact_status(row, complete),
                      "content_complete": bool(row["content_complete"]), "manifest_complete": complete}
        _session(gateway, token, value.expected_session_id)
        return result
    finally:
        conn.close()


def list_artifacts(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeArtifactList.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    conn = _connection(gateway)
    try:
        # Keep task revision, manifest and page in the same SQLite read snapshot.
        with conn:
            conn.execute("BEGIN")
            task = _artifact_task(conn, context, value)
            result = _artifact_page(conn, task, limit=value.limit, cursor=value.cursor)
    finally:
        conn.close()
    result = _audit(gateway, context, "native_tasks.artifacts.list", result)
    _session(gateway, token, value.expected_session_id)
    return result


def read_artifact(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeArtifactRead.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    conn = _connection(gateway)
    try:
        with conn:
            conn.execute("BEGIN")
            task = _artifact_task(conn, context, value)
            row = conn.execute("SELECT a.* FROM native_task_artifact_versions v JOIN native_task_artifacts a "
                               "ON a.source_id=v.source_id AND a.session_id=v.session_id AND a.artifact_id=v.artifact_id "
                               "WHERE v.source_id=? AND v.session_id=? AND v.source_revision=? AND v.artifact_id=?", (
                                   value.source_id, value.session_id, value.source_revision, value.artifact_id,
                               )).fetchone()
            if row is None:
                raise KeyError("artifact reference has not been delivered")
            artifact = _artifact_status(row, _manifest(conn, task))
            result = {"source_revision": value.source_revision, "artifact": artifact, "offset": value.offset, "next_offset": None}
            if artifact["delivery_status"] == "available":
                if value.offset > artifact["bytes"] or (value.offset == artifact["bytes"] and value.offset != 0):
                    raise ValueError("artifact chunk offset exceeds original length")
                chunk = conn.execute("SELECT chunk,chunk_sha256 FROM native_task_artifact_chunks "
                                     "WHERE source_id=? AND session_id=? AND artifact_id=? AND offset=?", (
                                         value.source_id, value.session_id, value.artifact_id, value.offset,
                                     )).fetchone()
                if chunk is None or hashlib.sha256(chunk["chunk"]).hexdigest() != chunk["chunk_sha256"]:
                    raise ValueError("artifact chunk is missing or damaged")
                next_offset = value.offset + len(chunk["chunk"])
                result.update({"content": base64.b64encode(chunk["chunk"]).decode("ascii"), "encoding": "base64",
                               "chunk_sha256": chunk["chunk_sha256"],
                               "next_offset": next_offset if next_offset < artifact["bytes"] else None})
    finally:
        conn.close()
    result = _audit(gateway, context, "native_tasks.artifacts.read", result)
    _session(gateway, token, value.expected_session_id)
    return result


def list_tasks(gateway: IdentityGateway, token: str, payload: dict) -> dict:
    value = NativeTaskList.model_validate(payload)
    context = _session(gateway, token, value.expected_session_id)
    # Keyset ordering uses stable source/session IDs, so updated summaries cannot
    # jump across pages or cause another actor's rows to consume the page limit.
    filters = {"source_id": value.source_id, "root_session_id": value.root_session_id,
               "principal": "admin" if context.role == "admin" else _owner(context)}
    scope = sha256_hex(canonical_json(filters))
    clauses, args = [], []
    if context.role != "admin":
        clauses.append("owner_json=?")
        args.append(canonical_json(_owner(context)))
    if value.source_id:
        clauses.append("source_id=?")
        args.append(value.source_id)
    if value.root_session_id:
        clauses.append("root_session_id=?")
        args.append(value.root_session_id)
    if value.cursor:
        try:
            cursor = json.loads(base64.b64decode(value.cursor, altchars=b"-_", validate=True))
            if (not isinstance(cursor, list) or len(cursor) != 3 or cursor[0] != scope or
                    not all(isinstance(item, str) for item in cursor)):
                raise ValueError("invalid cursor")
        except (ValueError, UnicodeError) as error:
            raise ValueError("native task cursor does not match the current query") from error
        clauses.append("(source_id>? OR (source_id=? AND session_id>?))")
        args.extend([cursor[1], cursor[1], cursor[2]])
    conn = _connection(gateway)
    try:
        conn.execute("BEGIN")
        rows = conn.execute(native_task_migration.records_sql() + "SELECT * FROM native_task_records" + (" WHERE " + " AND ".join(clauses) if clauses else "") +
                            " ORDER BY source_id,session_id LIMIT ?", [*args, value.limit + 1]).fetchall()
        tasks, legacy_pending = [], []
        for row in rows[:value.limit]:
            _authorize(context, row)
            if native_task_migration.legacy(row):
                legacy_pending.append(native_task_migration.pending(conn, row))
            else:
                tasks.append(_summary(row))
    finally:
        conn.close()
    last = rows[value.limit - 1] if len(rows) > value.limit else None
    cursor = base64.urlsafe_b64encode(canonical_json([scope, last["source_id"], last["session_id"]]).encode()).decode() if last else None
    result = _audit(gateway, context, "native_tasks.list", {"tasks": tasks, "legacy_pending": legacy_pending, "next_cursor": cursor})
    _session(gateway, token, value.expected_session_id)
    return result
