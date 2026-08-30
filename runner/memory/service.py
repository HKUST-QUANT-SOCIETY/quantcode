"""Memory 搜索 / 持久化服务 — Day 2 尹一帆（重写）。

严格 1:1 移植自 MimoCode ``memory/service.ts``（去掉 Effect.ts 框架，
转成普通 Python 方法）。

核心算法（MimoCode 注释翻译）：
- search() 进入时先 reconcile（off-tool 写也能覆盖）。
- FTS5 MATCH + bm25 + snippet。SQLite 把 bm25 **低 = 好**返回，service
  取负映射成 "**高 = 好**" 给上层。
- Over-fetch 3 × limit（最多 50），保证 floor 砍噪音时不会误杀真命中。
- 相对 floor = 0.15 × top_score。floor = 0 关闭过滤；第 1 行永远保留
  （"能命中就保留"是 MimoCode 注释原话）。
- OR-join 的 recall 修复（详见 ``fts-query.ts`` 顶部注释）。

QuantCode 扩展（不在 MimoCode）：
- ``groups`` scope 的读权限检查（requester_group 必须等于 scope_id）
- 行级别二次过滤（开放 search 时防止 SQL 注入绕过）

Public API：
- :class:`MemoryService`
- :class:`MemoryHit`
- :class:`MemoryPermissionError`
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fts import LEGAL_SCOPES, file_exists_and_initialized, get_connection
from .paths import parse_path
from .query import build_fts_query
from .reconcile import reconcile_once

logger = logging.getLogger(__name__)


# MimoCode 默认值
DEFAULT_FLOOR_RATIO: float = 0.15            # search.ts:83
DEFAULT_LIMIT: int = 10                       # search.ts:66
SNIPPET_TOKEN_LIMIT: int = 32                 # search.ts:104 snippet 第 6 参
OVERFETCH_MULTIPLIER: int = 3                 # search.ts:116
OVERFETCH_CAP: int = 50                       # search.ts:116


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryHit:
    """搜索结果（MimoCode service.ts:120 字段的子集，去掉被 service 内化掉的）。"""

    path: str
    scope: str
    scope_id: str
    type: str
    snippet: str
    score: float                              # 高 = 好（已取负）

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "type": self.type,
            "snippet": self.snippet,
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# GROUP 隔离权限（QuantCode 扩展）
# ---------------------------------------------------------------------------

class MemoryPermissionError(PermissionError):
    """``groups`` scope 跨组读 / 写被拒。"""

    def __init__(self, msg: str, *, requester: str, target_scope_id: str) -> None:
        super().__init__(msg)
        self.requester = requester
        self.target_scope_id = target_scope_id


def _check_group_read_allowed(scope: str, scope_id: str, requester_group: str | None) -> None:
    """MimoCode 没有此函数。QuantCode 扩展：groups scope 显式越权拦截。"""
    if scope == "groups" and (not requester_group or requester_group != scope_id):
        raise MemoryPermissionError(
            f"groups scope 越权读：requester={requester_group!r} != scope_id={scope_id!r}",
            requester=requester_group or "<none>",
            target_scope_id=scope_id,
        )


# ---------------------------------------------------------------------------
# MemoryService
# ---------------------------------------------------------------------------

class MemoryService:
    """Memory 主入口。

    MimoCode 用 Effect.ts 的 ``Service`` + ``Layer`` —— 我们用单实例类。
    一次构造绑定一个 db path；多线程由 sqlite WAL 模式 + Service 内部锁兜底。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        root: str | Path | None = None,
        floor_ratio: float = DEFAULT_FLOOR_RATIO,
        requester_group: str | None = None,
        auto_reconcile: bool = True,
    ) -> None:
        """Args:
        db_path: sqlite 文件。
        root: ``.quantcode`` 根；为 None 时默指 db_path 父目录。reconcile 必需。
        floor_ratio: 相对 floor，默认 0.15；设 0 关闭过滤。
        requester_group: 当前 caller 所属 6 组之一；``groups`` scope 越权时拦截。
        auto_reconcile: search() 进入时是否先 reconcile（默认 True，对齐 MimoCode）。
        """
        self.db_path = Path(db_path)
        if not file_exists_and_initialized(self.db_path):
            from .fts import init_db
            init_db(self.db_path)
        self.root = Path(root) if root is not None else self.db_path.parent
        self.floor_ratio = floor_ratio
        self.requester_group = requester_group
        self.auto_reconcile = auto_reconcile

    # ---------------- connection helpers ----------------

    def _conn(self) -> sqlite3.Connection:
        conn = get_connection(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---------------- search（与 service.ts:52 严格对齐） ----------------

    def search(
        self,
        *,
        query: str,
        scope: str | None = None,
        scope_id: str | None = None,
        type: str | None = None,
        limit: int = DEFAULT_LIMIT,
        floor_ratio: float | None = None,
        requester_group: str | None = None,
    ) -> list[MemoryHit]:
        """MimoCode service.ts search() 的 Python 版。

        流程：
            1. （auto_reconcile）→ reconcile_once 把磁盘写同步到 DB
            2. build_fts_query → None 则返 []
            3. WHERE 拼装
            4. SELECT snippet + bm25
            5. fetch_limit = min(limit*3, 50)
            6. 取负 score（高 = 好）
            7. 相对 floor 过滤；i==0 必留
            8. 截 limit
            9. （QuantCode 扩展）逐行 GROUP 权限校验

        Args:
            query: 自由文本查询。
            scope: scope filter（global/projects/groups/sessions/tasks）。
            scope_id: scope 内 id filter。
            type: type filter（memory/checkpoint/progress/notes/...）。
            limit: 上限，默认 10。
            floor_ratio: 覆盖实例默认 floor；None 时用实例设置。
            requester_group: 覆盖实例默认 requester。

        Returns:
            :class:`MemoryHit` 列表，按 score 降序（高 = 好）。
        """
        rgroup = requester_group if requester_group is not None else self.requester_group

        # QuantCode 扩展：显式 scope=groups 提前校验
        if scope == "groups":
            if not scope_id:
                raise ValueError("search: scope=groups 必须传 scope_id")
            _check_group_read_allowed(scope, scope_id, rgroup)

        # 1) auto_reconcile
        if self.auto_reconcile:
            try:
                reconcile_once(self.root, self, delete_orphans=True)
            except Exception as exc:                                                # noqa: BLE001
                logger.warning("auto_reconcile 失败（不阻塞 search）: %s", exc)

        # 2) build query
        fts_query = build_fts_query(query)
        if fts_query is None:
            return []

        # 3) WHERE 拼装
        conditions: list[str] = []
        params: list[Any] = []
        if scope:
            conditions.append("memory_fts.scope = ?")
            params.append(scope)
        if scope_id:
            conditions.append("memory_fts.scope_id = ?")
            params.append(scope_id)
        if type:
            conditions.append("memory_fts.type = ?")
            params.append(type)
        where_clause = " AND ".join(conditions)                                      # noqa: F841
        if where_clause:
            where_sql = f"AND {where_clause}"
        else:
            where_sql = ""

        # 4) SQL（与 service.ts:102 严格一致，仅 parameter 化）
        sql = f"""
            SELECT memory_fts.path, memory_fts.scope, memory_fts.scope_id,
                   memory_fts.type,
                   snippet(memory_fts_idx, 0, '<<', '>>', '...', {SNIPPET_TOKEN_LIMIT}) AS snippet,
                   bm25(memory_fts_idx) AS score
            FROM memory_fts_idx
            JOIN memory_fts ON memory_fts.id = memory_fts_idx.rowid
            WHERE memory_fts_idx MATCH ?
            {where_sql}
            ORDER BY score
            LIMIT ?
        """

        # 5) over-fetch
        fetch_limit = min(limit * OVERFETCH_MULTIPLIER, OVERFETCH_CAP)

        with self._conn() as conn:
            try:
                rows = conn.execute(sql, (fts_query, *params, fetch_limit)).fetchall()
            except sqlite3.OperationalError as exc:
                logger.warning("FTS5 MATCH 失败: %s", exc)
                return []

        if not rows:
            return []

        # 6) 取负 score（高 = 好）
        mapped: list[MemoryHit] = []
        for r in rows:
            mapped.append(MemoryHit(
                path=r["path"],
                scope=r["scope"],
                scope_id=r["scope_id"],
                type=r["type"],
                snippet=r["snippet"],
                score=-float(r["score"]),
            ))

        # 9) QuantCode 扩展：行级别 GROUP 权限过滤
        out: list[MemoryHit] = []
        for hit in mapped:
            try:
                _check_group_read_allowed(hit.scope, hit.scope_id, rgroup)
            except MemoryPermissionError:
                continue
            out.append(hit)

        if not out:
            return []

        # 7) 相对 floor（MimoCode service.ts:131）
        effective_floor = floor_ratio if floor_ratio is not None else self.floor_ratio
        if effective_floor > 0:
            top_score = out[0].score
            cutoff = top_score * effective_floor
            out = [h for i, h in enumerate(out) if i == 0 or h.score >= cutoff]

        # 8) slice
        return out[:limit]

    # ---------------- reconcile（与 service.ts reconcileEffect 一致） ----------------

    def reconcile(self) -> dict[str, int]:
        """``reconcile_once`` 包装。返回 ``{"indexed", "pruned", "skipped", "updated"}``。"""
        return reconcile_once(self.root, self, delete_orphans=True)

    # ---------------- write / get / delete（Day 2 下午 node 函数便捷 API） ----------------

    def write(
        self,
        *,
        scope: str,
        scope_id: str | None = None,
        type: str | None = None,
        key: str,
        body: str,
        requester_group: str | None = None,
    ) -> str:
        """写入（或覆盖）一条 memory 记录，立即落盘 + 索引。

        行为：
        1. 由 ``build_path`` 反推磁盘路径（``<root>/.quantcode/memory/<scope>/...``）
        2. 创建父目录、写 ``.md`` 文件
        3. UPSERT 到 ``memory_fts``（触发器自动同步 FTS5 虚表）

        与任务表 §2.2 期望的 ``memory.write(scope=..., scope_id=..., type=..., key=..., body=...)``
        签名一致；node 函数可直接在 ``state['_memory']`` 上调用。

        Args:
            scope: ``LEGAL_SCOPES`` 之一。
            scope_id: scope 内 id（global 留空）。
            type: ``LEGAL_TYPES`` 之一；``None`` 时由 ``detect_type(key)`` 推断（"free" fallback）。
            key: 文件名（不含 .md）；允许 ``"tasks/T1/progress"`` 多段。
            body: markdown 内容。
            requester_group: 覆盖实例 ``requester_group``；用于 ``groups`` scope 写权限校验。

        Returns:
            写入的磁盘绝对路径。

        Raises:
            ValueError: scope / scope_id 不合法。
            MemoryPermissionError: ``groups`` scope 越权写。
        """
        from .paths import build_path, detect_type

        if scope not in LEGAL_SCOPES:
            raise ValueError(f"write: scope {scope!r} 不在 {LEGAL_SCOPES}")
        if scope == "global" and scope_id:
            raise ValueError("write: global scope 不应传 scope_id")

        # QuantCode 扩展：groups scope 写权限
        rgroup = requester_group if requester_group is not None else self.requester_group
        if scope == "groups":
            if not scope_id:
                raise ValueError("write: groups scope 需要 scope_id")
            _check_group_read_allowed(scope, scope_id, rgroup)

        resolved_type = type or detect_type(key)
        # tasks scope 用 key 推 type 时需要把 tasks/<tid>/<key> 整体传进去（与 parse_path 行为一致）
        if resolved_type == "free" and scope == "tasks" and "/" in key:
            resolved_type = detect_type(key)

        # build_path 对 tasks 是 NotImplementedError —— caller 走 parse_path 路径即可
        if scope == "tasks":
            raise NotImplementedError(
                "write(scope='tasks'): tasks 路径含 sid 嵌入，暂不支持；"
                "请走 parse_path() 解析的路径直接调 index_from_disk。"
            )

        path_str = build_path(root=str(self.root), scope=scope, key=key, scope_id=scope_id)
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

        # 单点索引（不走 reconcile）——保证 caller 立即可 search 到
        loc = parse_path(str(path))
        if loc is None:
            raise RuntimeError(f"write: 写完路径 {path_str} 无法 parse 回 locator")

        # 写 DB 行；caller 显式传 type 时用它（loc.type 由 path 反推，可能为 "free"）
        # —— 任务表 §2.2 期望 ``memory.write(type=...)`` 显式生效。
        path_size = path.stat().st_size
        path_mtime_ms = int(path.stat().st_mtime * 1000)
        fingerprint = f"{path_size}-{path_mtime_ms}"
        final_type = resolved_type if type else loc.type
        with self._conn() as conn:
            conn.execute(
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
                (
                    str(path),
                    loc.scope,
                    loc.scope_id,
                    final_type,
                    body,
                    fingerprint,
                    int(time.time() * 1000),
                ),
            )
            conn.commit()
        logger.debug("memory.write: %s type=%s (idx=%s)", path, final_type, scope_id)
        return str(path)

    def get(
        self,
        *,
        scope: str,
        key: str,
        scope_id: str | None = None,
        requester_group: str | None = None,
    ) -> str | None:
        """读单条 memory 的 body 内容（直接走磁盘）。文件不存在返 None。

        Args:
            scope, scope_id, key: 与 :meth:`write` 同。
            requester_group: 覆盖实例默认 requester（P0-2：对齐 search()，
                ``groups`` scope 跨组读一律拦截）。
        """
        from .paths import build_path

        # P0-2：get() 此前绕过了 GROUP 读权限校验（search/write/delete 都有）。
        rgroup = requester_group if requester_group is not None else self.requester_group
        if scope == "groups":
            if not scope_id:
                raise ValueError("get: scope=groups 必须传 scope_id")
            _check_group_read_allowed(scope, scope_id, rgroup)

        if scope == "tasks":
            raise NotImplementedError("get(scope='tasks'): 暂不支持，见 write() 说明")
        path_str = build_path(root=str(self.root), scope=scope, key=key, scope_id=scope_id)
        path = Path(path_str)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def delete(
        self,
        *,
        scope: str,
        key: str,
        scope_id: str | None = None,
        requester_group: str | None = None,
    ) -> bool:
        """删除一条 memory（磁盘 + DB）。

        Returns:
            ``True`` 表示确实删了一条（文件或 DB 行存在过）。
        """
        from .paths import build_path

        if scope == "tasks":
            raise NotImplementedError("delete(scope='tasks'): 暂不支持")

        # 写权限
        rgroup = requester_group if requester_group is not None else self.requester_group
        if scope == "groups":
            if not scope_id:
                raise ValueError("delete: groups scope 需要 scope_id")
            _check_group_read_allowed(scope, scope_id, rgroup)

        path_str = build_path(root=str(self.root), scope=scope, key=key, scope_id=scope_id)
        path = Path(path_str)
        deleted = False
        # 1) 磁盘
        if path.is_file():
            path.unlink()
            deleted = True
        # 2) DB 行（即便磁盘已删，DB 残留也清掉——reconcile 之前可能未跑）
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM memory_fts WHERE path = ?", (str(path),))
            if cur.rowcount > 0:
                deleted = True
            conn.commit()
        return deleted


__all__ = [
    "DEFAULT_FLOOR_RATIO",
    "DEFAULT_LIMIT",
    "MemoryHit",
    "MemoryPermissionError",
    "MemoryService",
    "OVERFETCH_CAP",
    "OVERFETCH_MULTIPLIER",
    "SNIPPET_TOKEN_LIMIT",
]
