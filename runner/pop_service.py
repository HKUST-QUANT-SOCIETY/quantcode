"""SQLite-backed Pop dedupe/read/ack service."""
from __future__ import annotations

import json
import base64
import sqlite3
from pathlib import Path

from schemas.pop import Pop


class PopService:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS pops (
                    dedupe_key TEXT PRIMARY KEY,
                    pop_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                )"""
            )

    def list_scoped(self, *, actor_id: str, repositories: set[str],
                    unread_only: bool = False, limit: int = 100) -> list[Pop]:
        return self.page_scoped(actor_id=actor_id, repositories=repositories,
                                unread_only=unread_only, limit=limit)["pops"]

    def page_scoped(self, *, actor_id: str, repositories: set[str],
                    unread_only: bool = False, limit: int = 100, cursor: str | None = None) -> dict:
        if not actor_id:
            raise PermissionError("Pop requires an authenticated actor")
        if not 1 <= limit <= 200:
            raise ValueError("Pop limit must be between 1 and 200")
        before = None
        if cursor:
            try:
                before = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if not isinstance(before, list) or len(before) != 2 or not all(isinstance(value, str) for value in before):
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError) as exc:
                raise ValueError("invalid Pop cursor") from exc
        with self._conn() as conn:
            self._receipts(conn)
            rows = conn.execute(
                "SELECT p.payload, r.read_status, r.ack_status, p.observed_at, p.pop_id FROM pops p "
                "LEFT JOIN pop_receipts r ON r.pop_id=p.pop_id AND r.actor_id=? "
                "ORDER BY p.observed_at DESC, p.pop_id DESC", (actor_id,),
            )
            result = []
            positions = []
            unread_count = 0
            for payload, read_status, ack_status, observed_at, pop_id in rows:
                pop = Pop.model_validate_json(payload)
                if (pop.repository or pop.repo_or_package) not in repositories:
                    continue
                # A legacy global acknowledgement must not mark another
                # person's notification as read.
                pop = pop.model_copy(update={"read_status": read_status or "unread",
                                             "ack_status": ack_status or "pending"})
                if pop.read_status == "unread":
                    unread_count += 1
                if before and (observed_at, pop_id) >= tuple(before):
                    continue
                if unread_only and pop.read_status != "unread":
                    continue
                if len(result) <= limit:
                    result.append(pop)
                    positions.append([observed_at, pop_id])
            more = len(result) > limit
            return {"pops": result[:limit], "unread_count": unread_count,
                    "next_cursor": base64.urlsafe_b64encode(json.dumps(positions[limit - 1]).encode()).decode() if more else None}

    @staticmethod
    def _receipts(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS pop_receipts ("
                     "actor_id TEXT NOT NULL, pop_id TEXT NOT NULL, "
                     "read_status TEXT NOT NULL DEFAULT 'unread', "
                     "ack_status TEXT NOT NULL DEFAULT 'pending', "
                     "PRIMARY KEY(actor_id,pop_id))")

    def update_scoped(self, pop_id: str, *, actor_id: str, repositories: set[str],
                      read: bool | None = None, ack: bool | None = None) -> Pop:
        if not actor_id:
            raise PermissionError("Pop requires an authenticated actor")
        with self._conn() as conn:
            self._receipts(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM pops WHERE pop_id=?", (pop_id,)).fetchone()
            if row is None:
                raise PermissionError("Pop not found in the current scope")
            pop = Pop.model_validate_json(row[0])
            if (pop.repository or pop.repo_or_package) not in repositories:
                raise PermissionError("Pop not found in the current scope")
            conn.execute("INSERT OR IGNORE INTO pop_receipts(actor_id,pop_id) VALUES(?,?)", (actor_id, pop_id))
            for field, value in (("read_status", None if read is None else "read" if read else "unread"),
                                 ("ack_status", None if ack is None else "acknowledged" if ack else "pending")):
                if value is not None:
                    conn.execute(f"UPDATE pop_receipts SET {field}=? WHERE actor_id=? AND pop_id=?", (value, actor_id, pop_id))
            receipt = conn.execute("SELECT read_status,ack_status FROM pop_receipts WHERE actor_id=? AND pop_id=?", (actor_id, pop_id)).fetchone()
            return pop.model_copy(update={"read_status": receipt[0], "ack_status": receipt[1]})

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    def put(self, pop: Pop) -> bool:
        """Insert once by dedupe_key. Returns False for a duplicate."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO pops(dedupe_key,pop_id,payload,observed_at) VALUES(?,?,?,?)",
                (
                    pop.dedupe_key,
                    pop.pop_id,
                    pop.model_dump_json(),
                    pop.observed_at.isoformat(),
                ),
            )
            return cur.rowcount == 1

    def list(self, *, unread_only: bool = False, limit: int = 100) -> list[Pop]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM pops ORDER BY observed_at DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
        pops = [Pop.model_validate(json.loads(row[0])) for row in rows]
        return [pop for pop in pops if pop.read_status == "unread"] if unread_only else pops

    def update_status(self, pop_id: str, *, read: bool | None = None, ack: bool | None = None) -> Pop:
        with self._conn() as conn:
            row = conn.execute("SELECT dedupe_key,payload FROM pops WHERE pop_id=?", (pop_id,)).fetchone()
            if row is None:
                raise KeyError(pop_id)
            pop = Pop.model_validate(json.loads(row[1]))
            changes = {}
            if read is not None:
                changes["read_status"] = "read" if read else "unread"
            if ack is not None:
                changes["ack_status"] = "acknowledged" if ack else "pending"
            pop = pop.model_copy(update=changes)
            conn.execute("UPDATE pops SET payload=? WHERE dedupe_key=?", (pop.model_dump_json(), row[0]))
            return pop


__all__ = ["PopService"]
