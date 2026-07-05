from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas import (
    BlackboardEntry,
    BlackboardScope,
    BlackboardState,
    GroupName,
    WritePolicy,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BLACKBOARD_DB = PROJECT_ROOT / ".quantcode" / "blackboard.db"
DEFAULT_SESSION_ID = "S0000000000000001"


class BlackboardPermissionError(PermissionError):
    """Raised when a caller crosses a hard GROUP-scope boundary."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_scope(scope: BlackboardScope | str) -> BlackboardScope:
    if isinstance(scope, BlackboardScope):
        return scope
    return BlackboardScope(scope)


def _coerce_group(group: GroupName | str | None) -> GroupName | None:
    if group is None or isinstance(group, GroupName):
        return group
    return GroupName(group)


class BlackboardService:
    """SQLite-backed store for :class:`schemas.BlackboardState` entries.

    The service intentionally enforces a small v1 policy:
    PROJECT entries are readable by every group, while GROUP entries are only
    visible to their owning group. Cross-group handoff data must therefore be
    written to PROJECT scope.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        session_id: str = DEFAULT_SESSION_ID,
        requester_group: GroupName | str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_BLACKBOARD_DB
        self.session_id = session_id
        self.requester_group = _coerce_group(requester_group)
        self._init_db()

    def _init_db(self) -> None:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS blackboard_entries (
                    session_id TEXT NOT NULL,
                    entry_key TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    group_name TEXT,
                    key TEXT NOT NULL,
                    entry_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, entry_key)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_blackboard_scope
                ON blackboard_entries (session_id, scope, group_name)
                """
            )
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _effective_group(self, requester_group: GroupName | str | None) -> GroupName | None:
        if requester_group is None:
            return self.requester_group
        return _coerce_group(requester_group)

    @staticmethod
    def _entry_key(scope: BlackboardScope, group: GroupName | None, key: str) -> str:
        return BlackboardState.make_entry_key(scope, group, key)

    @staticmethod
    def _read_allowed(entry: BlackboardEntry, requester_group: GroupName | None) -> bool:
        if entry.scope != BlackboardScope.GROUP:
            return True
        return requester_group is not None and entry.group == requester_group

    @staticmethod
    def _assert_write_allowed(
        entry: BlackboardEntry,
        requester_group: GroupName | None,
    ) -> None:
        if requester_group is not None and entry.written_by_group != requester_group:
            raise BlackboardPermissionError(
                "written_by_group must match requester_group"
            )
        if entry.scope == BlackboardScope.GROUP:
            if entry.group is None:
                raise ValueError("GROUP scope requires group")
            if entry.written_by_group != entry.group:
                raise BlackboardPermissionError(
                    "GROUP scope writes must be written by the owning group"
                )
            if requester_group is not None and requester_group != entry.group:
                raise BlackboardPermissionError(
                    "requester_group cannot write another group's entry"
                )

    def _load_by_entry_key(self, entry_key: str) -> BlackboardEntry | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT entry_json
                FROM blackboard_entries
                WHERE session_id = ? AND entry_key = ?
                """,
                (self.session_id, entry_key),
            ).fetchone()
        if row is None:
            return None
        return BlackboardEntry.model_validate_json(row["entry_json"])

    def put(
        self,
        entry: BlackboardEntry,
        *,
        requester_group: GroupName | str | None = None,
    ) -> BlackboardEntry:
        """Insert or update an entry, incrementing version on overwrite."""

        effective_group = self._effective_group(requester_group)
        self._assert_write_allowed(entry, effective_group)
        json.dumps(entry.value)

        entry_key = self._entry_key(entry.scope, entry.group, entry.key)
        existing = self._load_by_entry_key(entry_key)
        data = entry.model_dump()
        now = _utc_now()
        if existing is not None:
            data["created_at"] = existing.created_at
            data["version"] = existing.version + 1
        data["updated_at"] = now
        stored = BlackboardEntry(**data)

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO blackboard_entries (
                    session_id, entry_key, scope, group_name, key, entry_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, entry_key) DO UPDATE SET
                    scope = excluded.scope,
                    group_name = excluded.group_name,
                    key = excluded.key,
                    entry_json = excluded.entry_json,
                    updated_at = excluded.updated_at
                """,
                (
                    self.session_id,
                    entry_key,
                    stored.scope.value,
                    stored.group.value if stored.group else None,
                    stored.key,
                    stored.model_dump_json(),
                    now.isoformat(),
                ),
            )
            conn.commit()
        return stored

    def write_value(
        self,
        *,
        scope: BlackboardScope | str,
        key: str,
        value: dict | list | str | int | float | bool | None,
        written_by_task_id: str,
        written_by_group: GroupName | str,
        group: GroupName | str | None = None,
        write_policy: WritePolicy | str = WritePolicy.OWNER,
        requester_group: GroupName | str | None = None,
    ) -> BlackboardEntry:
        """Convenience wrapper for writing a JSON-serializable value."""

        resolved_scope = _coerce_scope(scope)
        resolved_written_by = _coerce_group(written_by_group)
        resolved_group = _coerce_group(group)
        if resolved_scope == BlackboardScope.GROUP and resolved_group is None:
            resolved_group = resolved_written_by
        entry = BlackboardEntry(
            key=key,
            scope=resolved_scope,
            group=resolved_group,
            write_policy=WritePolicy(write_policy),
            value=value,
            written_by_task_id=written_by_task_id,
            written_by_group=resolved_written_by,
        )
        return self.put(entry, requester_group=requester_group)

    def get_entry(
        self,
        scope: BlackboardScope | str,
        group: GroupName | str | None,
        key: str,
        *,
        requester_group: GroupName | str | None = None,
    ) -> BlackboardEntry | None:
        """Return a visible entry or ``None`` when absent or permission-blocked."""

        resolved_scope = _coerce_scope(scope)
        resolved_group = _coerce_group(group)
        entry_key = self._entry_key(resolved_scope, resolved_group, key)
        entry = self._load_by_entry_key(entry_key)
        if entry is None:
            return None
        if not self._read_allowed(entry, self._effective_group(requester_group)):
            return None
        return entry

    def list_entries(
        self,
        *,
        scope: BlackboardScope | str | None = None,
        group: GroupName | str | None = None,
        requester_group: GroupName | str | None = None,
    ) -> list[BlackboardEntry]:
        """List visible entries, optionally filtered by scope and group."""

        conditions = ["session_id = ?"]
        params: list[Any] = [self.session_id]
        if scope is not None:
            conditions.append("scope = ?")
            params.append(_coerce_scope(scope).value)
        if group is not None:
            conditions.append("group_name = ?")
            resolved_group = _coerce_group(group)
            params.append(resolved_group.value if resolved_group else None)

        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT entry_json
                FROM blackboard_entries
                WHERE {' AND '.join(conditions)}
                ORDER BY updated_at, entry_key
                """,
                tuple(params),
            ).fetchall()

        effective_group = self._effective_group(requester_group)
        entries = [BlackboardEntry.model_validate_json(row["entry_json"]) for row in rows]
        return [entry for entry in entries if self._read_allowed(entry, effective_group)]

__all__ = [
    "BlackboardPermissionError",
    "BlackboardService",
    "DEFAULT_BLACKBOARD_DB",
    "DEFAULT_SESSION_ID",
    "PROJECT_ROOT",
]
