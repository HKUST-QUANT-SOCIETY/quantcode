"""SQLite-backed Pop dedupe/read/ack service."""
from __future__ import annotations

import json
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
