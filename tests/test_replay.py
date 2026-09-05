"""replay 工具测试 — make_thread_id（task_id 格式/唯一性）+ scripts.replay（list/show）。

覆盖：
1. make_thread_id 不带 task_id：<group>-<flow>-<uuid8>，同秒同参不碰撞。
2. make_thread_id 带 task_id：<group>-<flow>-<task_id>-<uuid8>，同秒同参不碰撞。
3. 旧签名（ts/suffix）行为不变（向后兼容）。
4. replay list 对手工插行的 tmp checkpoints.db（LangGraph checkpoints 表结构）能列出
   DISTINCT thread + 最近 checkpoint；空库容错返回空。
"""
from __future__ import annotations

import sqlite3

from runner.langgraph_base import (
    CHECKPOINTS_DB,
    clear_checkpointer_cache,
    get_checkpointer,
    make_thread_id,
)
from scripts.replay import list_threads, main, show_thread


# ---------------------------------------------------------------------------
# make_thread_id
# ---------------------------------------------------------------------------

class TestMakeThreadId:
    def test_without_task_id_format_and_uniqueness(self):
        """默认格式 <group>-<flow>-<uuid8>；同秒同参不碰撞。"""
        first = make_thread_id("risk", "risk:ci")
        second = make_thread_id("risk", "risk:ci")
        for tid in (first, second):
            group, flow, unique = tid.split("-")
            assert group == "risk"
            assert flow == "risk_ci"
            assert len(unique) == 8
            int(unique, 16)  # uuid 截 8 位 hex
        assert first != second

    def test_with_task_id_format_and_uniqueness(self):
        """带 task_id 格式 <group>-<flow>-<task_id>-<uuid8>；同秒同参不碰撞。"""
        prefix = "factor-factor_evaluation-T42-"
        first = make_thread_id("factor", "factor:evaluation", task_id="T42")
        second = make_thread_id("factor", "factor:evaluation", task_id="T42")
        for tid in (first, second):
            assert tid.startswith(prefix)
            unique = tid[len(prefix):]
            assert len(unique) == 8
            int(unique, 16)
        assert first != second

    def test_legacy_ts_suffix_unchanged(self):
        """旧签名（ts/suffix）输出保持不变，已有测试/脚本不受影响。"""
        assert (
            make_thread_id("risk", "risk:ci", ts=10, suffix="agent-normal")
            == "risk-risk_ci-10-agent-normal"
        )
        assert make_thread_id("factor", "factor:evaluation", ts=1) == "factor-factor_evaluation-1"


# ---------------------------------------------------------------------------
# replay list / show
# ---------------------------------------------------------------------------

def _seed_checkpoints(db_path) -> None:
    """建真实 LangGraph checkpoints 表结构并手工插几行（容错：不用 saver 写入）。"""
    get_checkpointer(db_path).setup()  # 建表
    clear_checkpointer_cache()  # 释放 saver 连接，避免占用

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id,"
            " parent_checkpoint_id, type, checkpoint, metadata)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "risk-risk_ci-aaaa1111",
                    "",
                    "1ef4f797-8335-6428-8001-8a1503f9b875",
                    None,
                    "msgpack",
                    b"stub",
                    None,
                ),
                (
                    "risk-risk_ci-aaaa1111",
                    "",
                    "1ef4f798-8335-6428-8001-8a1503f9b875",
                    "1ef4f797-8335-6428-8001-8a1503f9b875",
                    "msgpack",
                    b"stub",
                    None,
                ),
                (
                    "factor-factor_evaluation-bbbb2222",
                    "",
                    "1ef4f797-8335-6428-8001-8a1503f9b876",
                    None,
                    "msgpack",
                    b"stub",
                    None,
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()


class TestReplayList:
    def test_lists_distinct_threads_with_latest_checkpoint(self, tmp_path):
        db = tmp_path / "checkpoints.db"
        _seed_checkpoints(db)

        threads = list_threads(db)
        ids = [t["thread_id"] for t in threads]
        assert sorted(ids) == [
            "factor-factor_evaluation-bbbb2222",
            "risk-risk_ci-aaaa1111",
        ]
        # DISTINCT：每个 thread 只出现一次
        assert len(ids) == len(set(ids))
        # 最近 checkpoint_id（同一 thread 两行，取 MAX）
        latest = {t["thread_id"]: t["checkpoint_id"] for t in threads}
        assert latest["risk-risk_ci-aaaa1111"] == "1ef4f798-8335-6428-8001-8a1503f9b875"

    def test_empty_db_tolerated(self, tmp_path):
        db = tmp_path / "empty.db"
        db.write_bytes(b"")  # 空文件，无 checkpoints 表
        assert list_threads(db) == []

    def test_main_list_prints_threads(self, tmp_path, capsys):
        db = tmp_path / "checkpoints.db"
        _seed_checkpoints(db)
        assert main(["list", "--db", str(db)]) == 0
        out = capsys.readouterr().out
        assert "risk-risk_ci-aaaa1111" in out
        assert "factor-factor_evaluation-bbbb2222" in out


class TestReplayShow:
    def test_show_thread_is_tolerant_with_stub_blob(self, tmp_path):
        db = tmp_path / "checkpoints.db"
        _seed_checkpoints(db)
        # stub blob 解码失败也要降级展示，不抛异常
        out = show_thread(db, "risk-risk_ci-aaaa1111")
        assert "risk-risk_ci-aaaa1111" in out
        assert "checkpoint_id" in out

    def test_show_missing_thread(self, tmp_path):
        db = tmp_path / "checkpoints.db"
        _seed_checkpoints(db)
        assert "thread 不存在" in show_thread(db, "nope-1")
