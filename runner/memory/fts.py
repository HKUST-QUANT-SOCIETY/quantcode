"""Memory FTS5 表结构与初始化 — Day 2 尹一帆（重写）。

1:1 移植自 MimoCode ``memory/fts.sql.ts`` 与 Drizzle 之外的 FTS5 虚表 + 触发器迁移。
QuantCode 扩展：
- ``groups`` scope（5 组隔离，MimoCode 没有）
- ``tasks`` scope（顶层，MimoCode 的 tasks 是嵌套在 sessions 下的多段 key；
  QuantCode 设计要求独立 scope 以便"查全部 task"而不必指定 session）

不引入 MimoCode 的 ``cc`` scope（CC 是 Claude Code 路径概念，与本项目无关）。

主要 API：
- :func:`init_db` —— 初始化（幂等）
- :func:`file_exists_and_initialized`
- :func:`get_connection`
- :data:`LEGAL_SCOPES` —— storage scope whitelist
- :data:`LEGAL_TYPES` —— 与 MimoCode 对齐
- :data:`SCHEMA_VERSION`
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


SCHEMA_VERSION = 1

# Four storage scopes. Task progress is Runtime State nested under sessions,
# not a top-level Memory scope.
LEGAL_SCOPES: tuple[str, ...] = (
    "global",
    "projects",
    "groups",     # QuantCode 扩展：6 组的隔离
    "sessions",
)

# 与 MimoCode `MemoryType` enum 1:1 对齐
LEGAL_TYPES: tuple[str, ...] = (
    "free",
    "memory",
    "checkpoint",
    "progress",
    "notes",
    "feedback",
    "project",
    "reference",
    "user",
)


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA foreign_keys=ON;",
)

# 主表 memory_fts —— 列定义与 MimoCode fts.sql.ts 严格一致
_DDL_TABLE = """
CREATE TABLE IF NOT EXISTS memory_fts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT UNIQUE NOT NULL,
    scope           TEXT NOT NULL,
    scope_id        TEXT NOT NULL DEFAULT '',
    type            TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    fingerprint     TEXT NOT NULL,
    last_indexed_at INTEGER NOT NULL
);
"""

# MimoCode 两个 index：scope_idx + type_idx
_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS memory_fts_scope_idx ON memory_fts(scope, scope_id);",
    "CREATE INDEX IF NOT EXISTS memory_fts_type_idx  ON memory_fts(type);",
)

# FTS5 虚表 + 同步触发器（按 MimoCode 习惯命名 `memory_fts_idx`）
_DDL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts_idx USING fts5(
    body,
    content='memory_fts',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
"""

_DDL_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memory_fts BEGIN
        INSERT INTO memory_fts_idx(rowid, body) VALUES (new.id, new.body);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memory_fts BEGIN
        INSERT INTO memory_fts_idx(memory_fts_idx, rowid, body)
        VALUES ('delete', old.id, old.body);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memory_fts BEGIN
        INSERT INTO memory_fts_idx(memory_fts_idx, rowid, body)
        VALUES ('delete', old.id, old.body);
        INSERT INTO memory_fts_idx(rowid, body) VALUES (new.id, new.body);
    END;
    """,
)

_DDL_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS memory_schema (
    version      INTEGER PRIMARY KEY,
    installed_at INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def init_db(db_path: str | Path) -> None:
    """初始化 memory 数据库（幂等）。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for pragma in _DDL_PRAGMAS:
            cur.execute(pragma)
        cur.execute(_DDL_TABLE)
        for idx_sql in _DDL_INDEXES:
            cur.execute(idx_sql)
        cur.execute(_DDL_FTS)
        for trig in _DDL_TRIGGERS:
            cur.execute(trig)
        cur.execute(_DDL_SCHEMA_VERSION)
        cur.execute(
            "INSERT OR IGNORE INTO memory_schema(version, installed_at) VALUES (?, ?)",
            (SCHEMA_VERSION, int(time.time())),
        )
        conn.commit()


def file_exists_and_initialized(db_path: str | Path) -> bool:
    """db 是否存在 + 基础表已建好。"""
    path = Path(db_path)
    if not path.exists():
        return False
    try:
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
            ).fetchone()
            return row is not None
    except sqlite3.DatabaseError:
        return False


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """取得一个 sqlite3.Connection（caller 负责 close）。

    测试 / debug 用。正式调用请走 :mod:`runner.memory.service`。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not file_exists_and_initialized(path):
        init_db(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


__all__ = [
    "LEGAL_SCOPES",
    "LEGAL_TYPES",
    "SCHEMA_VERSION",
    "file_exists_and_initialized",
    "get_connection",
    "init_db",
]
