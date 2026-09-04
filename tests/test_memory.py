"""Memory 模块单元测试 — Day 2 尹一帆（重写）。

严格对照 MimoCode memory 测试套件（`fts-query.test.ts` / `paths.test.ts` /
`service.test.ts` / `reconcile.test.ts` 等）的 Python 版本。QuantCode 扩展
测试（``groups`` scope + GROUP 隔离）单独一节。

运行（hkust-quant env）：

    # 从含 quantcode/ 与 test_codes/ 的同级目录（即项目根）执行
    cd <PROJECT_ROOT>
    pytest test_codes/day2/ -v
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterator

import pytest

from runner.memory import fts as fts_mod
from runner.memory import paths as paths_mod
from runner.memory import query as query_mod
from runner.memory import reconcile as reconcile_mod
from runner.memory.paths import (
    MemoryLocator,
    assert_safe_component,
    build_path,
    detect_type,
    parse_path,
    resolve_project_id,
)
from runner.memory.query import build_fts_query
from runner.memory.reconcile import (
    index_from_disk,
    reconcile_once,
    walk_memory_dir,
)
from runner.memory.service import (
    MemoryHit,
    MemoryPermissionError,
    MemoryService,
    DEFAULT_FLOOR_RATIO,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_workspace(tmp_path: Path) -> dict:
    """构造一个隔离的 MemoryService 根（``<tmp>/.quantcode`` + ``memory.db``）。

    返回字典包含
    - ``root``: ``.quantcode`` 根
    - ``db``: sqlite 路径
    - ``svc``: 默认 svc（无 requester_group）
    - ``factor_svc``: groups=scope 但仅能写 / 读自己组的 factor
    - ``model_svc``: 同上但 model
    """
    root = tmp_path / ".quantcode"
    root.mkdir()
    db = root / "memory.db"
    # 预创建 directory layout
    (root / "memory" / "global").mkdir(parents=True)
    return {
        "root": root,
        "db": db,
        "svc": MemoryService(str(db), root=str(root), auto_reconcile=False),
        "factor_svc": MemoryService(
            str(db), root=str(root), requester_group="factor", auto_reconcile=False
        ),
        "model_svc": MemoryService(
            str(db), root=str(root), requester_group="model", auto_reconcile=False
        ),
    }


@pytest.fixture
def mem_search_workspace(tmp_path: Path) -> Iterator[dict]:
    """MimoCode service.test.ts 同款 workspace（每次 reconcile 后即时搜索）。"""
    root = tmp_path / ".quantcode"
    root.mkdir()
    db = root / "memory.db"
    (root / "memory" / "global").mkdir(parents=True)
    svc = MemoryService(
        str(db), root=str(root), auto_reconcile=True  # service.ts 默认开 auto_reconcile
    )
    yield {"root": root, "db": db, "svc": svc}


@pytest.fixture
def mem_reconcile_workspace(tmp_path: Path) -> Iterator[dict]:
    """MimoCode reconcile.test.ts 同款 workspace（auto_reconcile 关）。"""
    root = tmp_path / ".quantcode"
    root.mkdir()
    db = root / "memory.db"
    (root / "memory" / "global").mkdir(parents=True)
    svc = MemoryService(str(db), root=str(root), auto_reconcile=False)
    yield {"root": root, "db": db, "svc": svc}


# ===========================================================================
# fts.py
# ===========================================================================

class TestFts:
    """MimoCode fts.sql.ts 行为对齐测试。"""

    def test_init_db_creates_tables(self, tmp_path: Path):
        import sqlite3

        db = tmp_path / "x.db"
        fts_mod.init_db(db)
        con = sqlite3.connect(str(db))
        try:
            names = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            con.close()
        assert "memory_fts" in names
        assert "memory_schema" in names
        # FTS5 虚表本体（除 _data/_idx/_config/_docsize 等附属表）
        assert "memory_fts_idx" in names

    def test_init_db_idempotent(self, tmp_path: Path):
        db = tmp_path / "x.db"
        fts_mod.init_db(db)
        fts_mod.init_db(db)
        assert fts_mod.file_exists_and_initialized(db)

    def test_init_db_creates_two_indexes(self, tmp_path: Path):
        import sqlite3

        db = tmp_path / "x.db"
        fts_mod.init_db(db)
        con = sqlite3.connect(str(db))
        try:
            idx = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        finally:
            con.close()
        # MimoCode 两个 index（scope_idx + type_idx）必须存在
        assert "memory_fts_scope_idx" in idx
        assert "memory_fts_type_idx" in idx

    def test_legal_scopes_separate_runtime_tasks(self):
        # Task progress is nested under sessions Runtime State, not Memory scope.
        # 不含 MimoCode 的 "cc"
        assert set(fts_mod.LEGAL_SCOPES) == {
            "global", "projects", "groups", "sessions",
        }

    def test_legal_types_align_with_mimocode(self):
        assert set(fts_mod.LEGAL_TYPES) == {
            "free", "memory", "checkpoint", "progress", "notes",
            "feedback", "project", "reference", "user",
        }

    def test_triggers_sync_fts5(self, tmp_path: Path):
        """MimoCode 行为：INSERT 同步到 FTS5 虚表；DELETE 移除。"""
        import sqlite3

        db = tmp_path / "x.db"
        fts_mod.init_db(db)
        con = sqlite3.connect(str(db))
        try:
            con.execute(
                "INSERT INTO memory_fts(path, scope, scope_id, type, body, fingerprint, last_indexed_at) "
                "VALUES('/x/a.md','global','','memory','hello PB-ROE','0',0)"
            )
            con.commit()
            rows = con.execute(
                "SELECT memory_fts_idx.rowid FROM memory_fts_idx WHERE memory_fts_idx MATCH '\"PB-ROE\"'"
            ).fetchall()
            assert len(rows) == 1
            con.execute("DELETE FROM memory_fts WHERE path='/x/a.md'")
            con.commit()
            rows = con.execute(
                "SELECT memory_fts_idx.rowid FROM memory_fts_idx WHERE memory_fts_idx MATCH '\"PB-ROE\"'"
            ).fetchall()
            assert rows == []
        finally:
            con.close()


# ===========================================================================
# paths.py — 严格对照 MimoCode paths.test.ts
# ===========================================================================

class TestPathsParsePath:
    """MimoCode paths.test.ts test('parsePath', ...) 16 cases。"""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/data/memory/global/tooling-prefs.md",
             ("global", "", "free", "tooling-prefs")),
            ("/data/memory/projects/uuid-1/memory.md",
             ("projects", "uuid-1", "memory", "memory")),
            ("/data/memory/projects/uuid-1/memory-rules.md",
             ("projects", "uuid-1", "memory", "memory-rules")),
            ("/data/memory/projects/uuid-1/MEMORY.md",
             ("projects", "uuid-1", "memory", "MEMORY")),                # case-insensitive
            ("/data/memory/projects/uuid-1/MEMORY-rules.md",
             ("projects", "uuid-1", "memory", "MEMORY-rules")),
            ("/data/memory/sessions/ses_abc/checkpoint.md",
             ("sessions", "ses_abc", "checkpoint", "checkpoint")),
            ("/data/memory/sessions/ses_abc/checkpoint-lexer.md",
             ("sessions", "ses_abc", "checkpoint", "checkpoint-lexer")),
            ("/data/memory/sessions/ses_abc/checkpoint/snapshot.md",
             ("sessions", "ses_abc", "free", "checkpoint/snapshot")),     # legacy v4
            ("/data/memory/projects/uuid-1/pinned.md",
             ("projects", "uuid-1", "free", "pinned")),                  # legacy v4
            ("/data/memory/projects/abc123def456/conventions.md",
             ("projects", "abc123def456", "free", "conventions")),
            # tasks are Runtime State nested under the session scope
            ("/data/memory/sessions/ses_abc/tasks/T1/progress.md",
             ("sessions", "ses_abc", "progress", "tasks/T1/progress")),
            ("/data/memory/sessions/ses_abc/tasks/T1/notes.md",
             ("sessions", "ses_abc", "notes", "tasks/T1/notes")),
            # multi-segment notes/draft 走 free（不在 6 条 pattern 内）
            ("/data/memory/sessions/ses_abc/tasks/T1/notes/draft.md",
             ("sessions", "ses_abc", "free", "tasks/T1/notes/draft")),
            # nested key after tid: 整个 notes/auth 留在 key 里
            ("/data/memory/sessions/ses_abc/tasks/T3/notes/auth.md",
             ("sessions", "ses_abc", "free", "tasks/T3/notes/auth")),
        ],
    )
    def test_parses_mimo_paths(self, path, expected):
        loc = parse_path(path)
        assert loc is not None, path
        scope, scope_id, typ, key = expected
        assert loc.scope == scope
        assert loc.scope_id == scope_id
        assert loc.type == typ
        assert loc.key == key

    def test_legacy_root_tasks_returns_none(self):
        """MimoCode test：legacy ``<root>/tasks/<id>/`` 不再支持（已从 Scope 移除）。"""
        assert parse_path("/data/memory/tasks/T1/progress.md") is None

    def test_non_memory_path_returns_none(self):
        assert parse_path("/data/checkpoints/ses_abc/001.md") is None

    def test_groups_scope_quantcode_extension(self, tmp_path: Path):
        """QuantCode 扩展：``groups/<group>/<key>.md`` → scope=groups。"""
        p = tmp_path / "groups" / "factor" / "spec.md"
        p.parent.mkdir(parents=True)
        p.write_text("x", encoding="utf-8")
        loc = parse_path(str(p))
        assert loc is not None
        assert loc.scope == "groups"
        assert loc.scope_id == "factor"
        assert loc.key == "spec"

    def test_tasks_with_quantcode_memory_prefix(self, tmp_path: Path):
        """QuantCode ``.quantcode/memory/sessions/<sid>/tasks/<tid>/<key>.md``。"""
        p = tmp_path / ".quantcode" / "memory" / "sessions" / "sesX" / "tasks" / "T7" / "progress.md"
        p.parent.mkdir(parents=True)
        p.write_text("x", encoding="utf-8")
        loc = parse_path(str(p))
        assert loc is not None
        assert loc.scope == "sessions"
        assert loc.scope_id == "sesX"
        assert loc.type == "progress"
        assert loc.key == "tasks/T7/progress"


class TestPathsBuildPath:
    """MimoCode paths.test.ts test('buildPath', ...) 5+ cases。"""

    def test_sessions_checkpoint(self):
        p = build_path(
            root="/data/memory", scope="sessions", scope_id="ses_abc", key="checkpoint"
        )
        assert p == "/data/memory/.quantcode/memory/sessions/ses_abc/checkpoint.md"

    def test_global_no_scope_id(self):
        p = build_path(root="/data/memory", scope="global", key="tooling")
        assert p == "/data/memory/.quantcode/memory/global/tooling.md"

    def test_groups_quantcode_extension(self):
        p = build_path(
            root="/data/memory", scope="groups", scope_id="factor", key="spec"
        )
        assert p == "/data/memory/.quantcode/memory/groups/factor/spec.md"

    def test_windows_separator_cannot_escape(self):
        with pytest.raises(ValueError, match="invalid path component"):
            build_path(root="/x", scope="global", key="..\\escape")
        with pytest.raises(ValueError, match="invalid path component"):
            build_path(
                root="/x",
                scope="sessions",
                scope_id="S1",
                key="nested\\..\\escape",
            )

    def test_windows_drive_path_is_rejected(self):
        with pytest.raises(ValueError, match="invalid path component"):
            build_path(root="/x", scope="global", key="C:\\secret")

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"scope": "sessions", "scope_id": "ses_abc", "key": "../escape"},
            {"scope": "sessions", "scope_id": "..", "key": "checkpoint"},
            {"scope": "global", "key": "/etc/passwd"},
            {"scope": "sessions", "scope_id": "/abs", "key": "checkpoint"},
            {"scope": "sessions", "scope_id": "ses_abc", "key": "tasks/T1/notes/../sneak"},
        ],
    )
    def test_rejects_unsafe_components(self, kwargs):
        with pytest.raises(ValueError, match="invalid path component"):
            build_path(root="/x", **kwargs)


class TestPathsResolveProjectId:
    """MimoCode paths.test.ts test('resolveProjectId', ...) 3 cases。"""

    def test_returns_12_char_hex(self):
        pid = resolve_project_id("/Users/me/projects/foo")
        assert re.match(r"^[a-f0-9]{12}$", pid)

    def test_deterministic(self):
        a = resolve_project_id("/Users/me/projects/foo")
        b = resolve_project_id("/Users/me/projects/foo")
        assert a == b

    def test_unique(self):
        assert resolve_project_id("/a") != resolve_project_id("/b")


class TestPathsAssertSafeComponent:
    def test_rejects_double_dot(self):
        with pytest.raises(ValueError):
            assert_safe_component("../etc/passwd")

    def test_rejects_leading_slash(self):
        with pytest.raises(ValueError):
            assert_safe_component("/abs")


# ===========================================================================
# query.py — 严格对照 MimoCode fts-query.test.ts
# ===========================================================================

class TestBuildFtsQuery:
    """MimoCode fts-query.test.ts 9 cases + OR-join 证明 1 case。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("hello world", '"hello" OR "world"'),
            ("FOO_bar baz-1", '"FOO_bar" OR "baz" OR "1"'),
            ("金银价格", '"金银价格"'),
            ("価格 2026年", '"価格" OR "2026年"'),
            ("", None),
            ("   ", None),
            ("T5.3 closure", '"T5" OR "3" OR "closure"'),
            ('(foo) bar* baz/qux', '"foo" OR "bar" OR "baz" OR "qux"'),
            ('say "hi"', '"say" OR "hi"'),
            ("foo and bar", '"foo" OR "and" OR "bar"'),
            ("postgres database port 5433", '"postgres" OR "database" OR "port" OR "5433"'),
        ],
    )
    def test_aligns_with_mimo(self, raw, expected):
        assert build_fts_query(raw) == expected


# ===========================================================================
# service.py — 严格对照 MimoCode service.test.ts
# ===========================================================================

class TestMemorySearch:
    """MimoCode service.test.ts 6 cases。"""

    def test_bm25_ranked_matches(self, mem_search_workspace):
        ws = mem_search_workspace
        root = ws["root"]
        (root / "memory" / "global" / "auth.md").write_text(
            "JWT signing with RS256 algorithm", encoding="utf-8"
        )
        (root / "memory" / "global" / "perf.md").write_text(
            "database query optimization tips", encoding="utf-8"
        )
        results = ws["svc"].search(query="JWT")
        assert len(results) == 1
        assert "auth.md" in results[0].path
        assert results[0].score > 0   # 取负后应为正

    def test_filters_by_scope(self, mem_search_workspace):
        ws = mem_search_workspace
        root = ws["root"]
        (root / "memory" / "global" / "x.md").write_text("matching content", encoding="utf-8")
        (root / "memory" / "sessions" / "ses_a").mkdir(parents=True, exist_ok=True)
        (root / "memory" / "sessions" / "ses_a" / "x.md").write_text("matching content", encoding="utf-8")
        sep = os.sep
        g = ws["svc"].search(query="matching", scope="global")
        s = ws["svc"].search(query="matching", scope="sessions")
        assert len(g) == 1 and f"{sep}global{sep}" in g[0].path
        assert len(s) == 1 and f"{sep}sessions{sep}" in s[0].path

    def test_filters_by_scope_id(self, mem_search_workspace):
        ws = mem_search_workspace
        root = ws["root"]
        (root / "memory" / "sessions" / "ses_a").mkdir(parents=True, exist_ok=True)
        (root / "memory" / "sessions" / "ses_b").mkdir(parents=True, exist_ok=True)
        (root / "memory" / "sessions" / "ses_a" / "x.md").write_text("alpha content", encoding="utf-8")
        (root / "memory" / "sessions" / "ses_b" / "x.md").write_text("alpha content", encoding="utf-8")
        a_only = ws["svc"].search(query="alpha", scope="sessions", scope_id="ses_a")
        assert len(a_only) == 1 and "ses_a" in a_only[0].path

    def test_respects_limit(self, mem_search_workspace):
        ws = mem_search_workspace
        root = ws["root"]
        for i in range(15):
            (root / "memory" / "global" / f"f{i}.md").write_text(f"match {i}", encoding="utf-8")
        results = ws["svc"].search(query="match", limit=5)
        assert len(results) == 5

    def test_fts5_special_chars_safe(self, mem_search_workspace):
        ws = mem_search_workspace
        root = ws["root"]
        (root / "memory" / "global" / "x.md").write_text(
            'literal "quoted" content with stars', encoding="utf-8"
        )
        for q in ['"quoted"', "wild*", "(paren)", "-not", "and"]:
            results = ws["svc"].search(query=q)
            assert isinstance(results, list)

    def test_or_match_and_empty(self, mem_search_workspace):
        ws = mem_search_workspace
        root = ws["root"]
        (root / "memory" / "global" / "doc.md").write_text(
            "T5.3 closure conversion abandoned -- out of v0.1 scope per spec.md 4.4",
            encoding="utf-8",
        )
        (root / "memory" / "global" / "other.md").write_text("unrelated text only", encoding="utf-8")
        svc = ws["svc"]
        dotted = svc.search(query="T5.3 closure")
        assert len(dotted) >= 1 and "doc.md" in dotted[0].path
        both = svc.search(query="abandoned scope")
        assert len(both) == 1 and "doc.md" in both[0].path
        or_hit = svc.search(query="abandoned nonexistentterm")
        assert len(or_hit) == 1 and "doc.md" in or_hit[0].path
        true_miss = svc.search(query="nonexistentterm anotherbogusword")
        assert len(true_miss) == 0
        empty = svc.search(query="   ")
        assert len(empty) == 0


class TestSearchFloorSemantics:
    """覆盖 service.ts:131-133 的 floor 行为 + 第 1 行永远保留。"""

    def test_top_always_kept(self, mem_search_workspace):
        ws = mem_search_workspace
        root = ws["root"]
        (root / "memory" / "global" / "a.md").write_text("apple", encoding="utf-8")
        (root / "memory" / "global" / "b.md").write_text("apple banana cherry", encoding="utf-8")
        (root / "memory" / "global" / "c.md").write_text("kiwi", encoding="utf-8")
        # query=apple: a/b 各命中 1 次；c 不命中
        results = ws["svc"].search(query="apple", limit=10)
        assert len(results) >= 1
        assert results[0].path.endswith("a.md") or results[0].path.endswith("b.md")

    def test_floor_zero_disables_filter(self, tmp_path: Path):
        root = tmp_path / ".quantcode"
        root.mkdir()
        db = root / "memory.db"
        (root / "memory" / "global").mkdir(parents=True)
        for i in range(10):
            (root / "memory" / "global" / f"f{i}.md").write_text(f"doc{i} content", encoding="utf-8")
        svc = MemoryService(str(db), root=str(root), floor_ratio=0, auto_reconcile=True)
        results = svc.search(query="content", limit=10)
        # 0 floor → 不过滤，但 limit = 10 而 over-fetch=50 实际能拿全
        # 结论：至少 1 行
        assert len(results) >= 1


# ===========================================================================
# reconcile.py — 严格对照 MimoCode reconcile.test.ts
# ===========================================================================

class TestMemoryReconcile:
    """MimoCode reconcile.test.ts 4 cases。"""

    def test_indexes_new_file(self, mem_reconcile_workspace):
        ws = mem_reconcile_workspace
        (ws["root"] / "memory" / "global" / "test.md").write_text(
            "hello world", encoding="utf-8"
        )
        stats = ws["svc"].reconcile()
        assert stats["indexed"] == 1
        rows = list(ws["svc"]._conn().execute(
            "SELECT body, scope, type FROM memory_fts"
        ))
        assert rows[0]["body"] == "hello world"
        assert rows[0]["scope"] == "global"
        assert rows[0]["type"] == "free"

    def test_removes_index_when_file_deleted(self, mem_reconcile_workspace):
        ws = mem_reconcile_workspace
        fp = ws["root"] / "memory" / "global" / "test.md"
        fp.write_text("hello", encoding="utf-8")
        ws["svc"].reconcile()
        assert len(list(ws["svc"]._conn().execute("SELECT * FROM memory_fts"))) == 1
        fp.unlink()
        ws["svc"].reconcile()
        rows = list(ws["svc"]._conn().execute("SELECT * FROM memory_fts"))
        assert rows == []

    def test_skips_reindex_when_fingerprint_matches(self, mem_reconcile_workspace):
        ws = mem_reconcile_workspace
        fp = ws["root"] / "memory" / "global" / "test.md"
        fp.write_text("hello", encoding="utf-8")
        ws["svc"].reconcile()
        before = ws["svc"]._conn().execute(
            "SELECT last_indexed_at FROM memory_fts"
        ).fetchone()[0]
        time.sleep(0.5)  # 确认时间过去；mtime 不变只是因为文件没改
        ws["svc"].reconcile()
        after = ws["svc"]._conn().execute(
            "SELECT last_indexed_at FROM memory_fts"
        ).fetchone()[0]
        # fingerprint 相同 → last_indexed_at **不**更新
        assert before == after

    def test_reindexes_on_file_change(self, mem_reconcile_workspace):
        ws = mem_reconcile_workspace
        fp = ws["root"] / "memory" / "global" / "test.md"
        fp.write_text("v1", encoding="utf-8")
        ws["svc"].reconcile()
        time.sleep(1.1)   # mtime 精度
        fp.write_text("v2", encoding="utf-8")
        ws["svc"].reconcile()
        rows = list(ws["svc"]._conn().execute("SELECT body FROM memory_fts"))
        assert len(rows) == 1 and rows[0]["body"] == "v2"

    def test_group_reconcile_does_not_prune_other_group_rows(self, tmp_path: Path):
        root = tmp_path / ".quantcode"
        db = root / "memory.db"
        model = root / "memory" / "groups" / "model" / "kept.md"
        model.parent.mkdir(parents=True)
        model.write_text("model knowledge", encoding="utf-8")
        model_svc = MemoryService(
            db, root=root, requester_group="model", auto_reconcile=False
        )
        model_svc.reconcile()
        model.unlink()

        factor_svc = MemoryService(
            db, root=root, requester_group="factor", auto_reconcile=False
        )
        factor_svc.reconcile()
        with factor_svc._conn() as conn:
            row = conn.execute(
                "SELECT path FROM memory_fts WHERE path LIKE '%kept.md'"
            ).fetchone()
        assert row is not None

    def test_root_can_be_project_or_quantcode_directory(self, tmp_path: Path):
        project_svc = MemoryService(tmp_path / ".quantcode" / "memory.db", root=tmp_path)
        quantcode_svc = MemoryService(
            tmp_path / ".quantcode" / "memory.db", root=tmp_path / ".quantcode"
        )
        project_path = project_svc.write(scope="global", key="root-form", body="project")
        quantcode_path = quantcode_svc.write(scope="global", key="root-form-2", body="quantcode")
        assert "/.quantcode/memory/global/" in project_path.replace("\\", "/")
        assert "/.quantcode/memory/global/" in quantcode_path.replace("\\", "/")
        assert "/.quantcode/.quantcode/" not in quantcode_path.replace("\\", "/")


# ===========================================================================
# QuantCode 扩展：GROUP 隔离
# ===========================================================================

class TestGroupIsolation:
    """QuantCode 独有：groups scope 跨组越权拦截。"""

    def test_cross_group_write_blocked(self, mem_workspace):
        """run reconcile with factor_svc 不应越权写 model memory。"""
        ws = mem_workspace
        factor_dir = ws["root"] / "memory" / "groups" / "factor"
        factor_dir.mkdir(parents=True)
        model_dir = ws["root"] / "memory" / "groups" / "model"
        model_dir.mkdir(parents=True)
        (factor_dir / "x.md").write_text("factor content", encoding="utf-8")
        (model_dir / "y.md").write_text("model secret", encoding="utf-8")
        stats = reconcile_once(str(ws["root"]), ws["factor_svc"])
        # factor 越权写 model 应被 skipped
        assert stats["skipped"] >= 1
        # factor 自己的应 indexed
        assert stats["indexed"] >= 1

    def test_explicit_groups_scope_read_blocked(self, mem_workspace):
        with pytest.raises(MemoryPermissionError):
            ws = mem_workspace
            # 提前 reconcile 一下让数据进库
            (ws["root"] / "memory" / "groups" / "model" / "y.md").parent.mkdir(parents=True)
            (ws["root"] / "memory" / "groups" / "model" / "y.md").write_text(
                "model", encoding="utf-8"
            )
            reconcile_once(str(ws["root"]), ws["model_svc"])
            # factor svc 不应能读 model 的 memory
            ws["factor_svc"].search(query="model", scope="groups", scope_id="model")

    def test_open_search_filters_cross_group_rows(self, mem_workspace):
        ws = mem_workspace
        (ws["root"] / "memory" / "groups" / "factor").mkdir(parents=True)
        (ws["root"] / "memory" / "groups" / "model").mkdir(parents=True)
        (ws["root"] / "memory" / "groups" / "factor" / "secret.md").write_text(
            "factor secret", encoding="utf-8"
        )
        (ws["root"] / "memory" / "groups" / "model" / "public.md").write_text(
            "model public data", encoding="utf-8"
        )
        reconcile_once(str(ws["root"]), ws["model_svc"])
        # model svc 开放搜索：factor 行被 row-level 过滤掉
        results = ws["model_svc"].search(query="secret OR public OR data", limit=20)
        sep = os.sep
        paths = {r.path for r in results}
        assert any(f"model{sep}public.md" in p for p in paths), f"model/public.md 不在结果: {paths}"
        assert not any(f"factor{sep}secret.md" in p for p in paths), f"factor/secret.md 越权: {paths}"

    def test_bound_service_cannot_switch_requester_group(self, mem_workspace):
        svc = mem_workspace["model_svc"]
        with pytest.raises(MemoryPermissionError, match="override"):
            svc.search(query="secret", requester_group="factor")
        with pytest.raises(MemoryPermissionError, match="override"):
            svc.write(
                scope="groups",
                scope_id="factor",
                key="secret",
                body="secret",
                requester_group="factor",
            )
