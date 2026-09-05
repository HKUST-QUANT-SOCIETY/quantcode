"""磁盘 ↔ SQLite 双向同步 — Day 2 尹一帆（重写）。

严格 1:1 移植自 MimoCode ``memory/reconcile.ts``，QuantCode 扩展：
- 单 root（QuantCode 没有 mimo + cc 双根的概念，只有 ``.quantcode/``）
- ``groups`` scope 写权限校验（用 ``MemoryService.requester_group``）

MimoCode 关键算法（保留）：
- 指纹 = ``"{stat.size}-{stat.mtimeMs}"``（精确字节级 + mtime 字符串）
- 索引流程：stat → fingerprint 同则 ``hit``（no-op），否则 UPSERT
- 修剪流程：先 **同时** 收集 mimo + cc 两根的磁盘路径合并成 set，然后从 DB
  中删除"不再在磁盘"的行（避免配 cc 时把 mimo 全删掉，反之亦然）

Public API：
- :func:`walk_memory_dir` —— 递归 ``.md``（MimoCode 同名）
- :func:`index_from_disk` —— 单文件 upsert
- :func:`reconcile_once` —— 全量同步入口（MimoCode ``reconcileMemory`` 的 QuantCode 单根版）
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from .fts import get_connection
from .paths import MemoryLocator, parse_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Disk walks
# ---------------------------------------------------------------------------

def walk_memory_dir(root: str | Path) -> list[Path]:
    """递归走 ``root`` 下所有 ``.md``，返回绝对路径列表。

    ENOENT 返回空（与 MimoCode reconcile.ts:12 行为一致），其他 OSError 抛出。
    """
    root = Path(root)
    out: list[Path] = []
    if not root.is_dir():
        return out

    def _recurse(dir_: Path) -> None:
        try:
            entries = list(dir_.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return
        for entry in entries:
            try:
                if entry.is_dir():
                    _recurse(entry)
                elif entry.is_file() and entry.name.endswith(".md"):
                    out.append(entry)
            except OSError:
                continue

    _recurse(root)
    return out


# ---------------------------------------------------------------------------
# Index one file（MimoCode reconcile.ts indexFromDisk 一致）
# ---------------------------------------------------------------------------

def _read_body(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def index_from_disk(
    abs_path: str | Path,
    loc: MemoryLocator,
    conn: sqlite3.Connection,
    *,
    old_fingerprint: str | None = None,
) -> str:
    """对单个文件做 index。

    Returns:
        ``"hit"``（无变更）/ ``"updated"``（写入或更新）

    Notes:
        - 指纹 = ``"{size}-{mtime_ms}"``，与 MimoCode 行为一致
        - 文件缺失返回 ``"skipped"``
        - UPSERT 到 memory_fts，并触发 FTS 虚表同步（触发器在 init_db 已建好）
    """
    path = Path(abs_path)
    try:
        st = path.stat()
    except FileNotFoundError:
        return "skipped"

    fingerprint = f"{st.st_size}-{int(st.st_mtime * 1000)}"  # 秒 → ms 与 MimoCode mtimeMs 对齐
    if old_fingerprint == fingerprint:
        return "hit"

    body = _read_body(path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO memory_fts (path, scope, scope_id, type, body, fingerprint, last_indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            scope=excluded.scope,
            scope_id=excluded.scope_id,
            type=excluded.type,
            body=excluded.body,
            fingerprint=excluded.fingerprint,
            last_indexed_at=excluded.last_indexed_at
        """,
        (str(path), loc.scope, loc.scope_id, loc.type, body, fingerprint, int(time.time() * 1000)),
    )
    return "updated"


# ---------------------------------------------------------------------------
# Reconcile entry
# ---------------------------------------------------------------------------

def reconcile_once(
    root: str | Path,
    service: "MemoryService",  # type: ignore[name-defined]  # noqa: F821
    *,
    delete_orphans: bool = True,
) -> dict[str, int]:
    """全量磁盘 ↔ DB 同步（QuantCode 单根 flavor）。

    流程（MimoCode reconcileMemory 同形）：
        1. walk_memory_dir(root) → disk_paths
        2. SELECT path, fingerprint FROM memory_fts → indexed Map
        3. prune: indexed 中不在 disk_paths 的 → DELETE
        4. index: 每条 disk path → index_from_disk(); "updated" 计数 +1
        5. GROUP 隔离：service.requester_group 不允许写别组 memory（如果 service 有该属性）

    Args:
        root: ``.quantcode`` 根。
        service: 一个 :class:`MemoryService` 实例；提供 db_path 与（可选）requester_group。
        delete_orphans: 是否删除磁盘已删但 DB 还存在的行。

    Returns:
        ``{"indexed": int, "pruned": int, "skipped": int, "errors": int}``
        （兼容 MimoCode 返回 ``{indexed, pruned}``，多两个字段便于诊断）。
    """
    rgroup = getattr(service, "requester_group", None)
    stats = {"indexed": 0, "pruned": 0, "skipped": 0, "errors": 0}

    disk_files = walk_memory_dir(root)
    disk_paths: set[str] = {str(p) for p in disk_files}

    db_path = service.db_path
    conn = get_connection(db_path)
    try:
        conn.row_factory = sqlite3.Row

        # 1) DB 已有 path + fingerprint
        indexed: dict[str, str] = {}
        for row in conn.execute("SELECT path, fingerprint FROM memory_fts"):
            indexed[row["path"]] = row["fingerprint"]

        # 2) Direction B: prune orphans
        if delete_orphans:
            for p in list(indexed.keys()):
                if p not in disk_paths:
                    # A group-scoped reconciler must never delete another
                    # group's index rows.  It may only maintain global,
                    # project/session rows and its own group namespace.
                    indexed_loc = parse_path(p)
                    if (
                        rgroup
                        and indexed_loc is not None
                        and indexed_loc.scope == "groups"
                        and indexed_loc.scope_id != rgroup
                    ):
                        continue
                    try:
                        cur = conn.execute("DELETE FROM memory_fts WHERE path = ?", (p,))
                        if cur.rowcount > 0:
                            stats["pruned"] += 1
                    except sqlite3.Error as exc:
                        logger.warning("prune failed for %s: %s", p, exc)
                        stats["errors"] += 1
            conn.commit()

        # 3) Direction A: index / reindex disk files
        for p in disk_files:
            loc = parse_path(str(p))
            if loc is None:
                logger.debug("reconcile: skip non-memory path %s", p)
                stats["skipped"] += 1
                continue
            # QuantCode 扩展：groups 写权限
            if loc.scope == "groups" and rgroup and rgroup != loc.scope_id:
                logger.debug("reconcile: skip cross-group %s (requester=%s)", p, rgroup)
                stats["skipped"] += 1
                continue
            try:
                old_fp = indexed.get(str(p))
                result = index_from_disk(p, loc, conn, old_fingerprint=old_fp)
                if result == "updated":
                    stats["indexed"] += 1
            except Exception as exc:                                                  # noqa: BLE001
                logger.warning("index failed for %s: %s", p, exc)
                stats["errors"] += 1
        conn.commit()
    finally:
        conn.close()

    return stats


__all__ = [
    "index_from_disk",
    "reconcile_once",
    "walk_memory_dir",
]
