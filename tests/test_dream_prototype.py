"""Dream 原型测试 — Day 4 尹一帆。

覆盖:
1. 主源 checkpoints.db 写一条 trace + 跑 dream → memory 命中
2. fallback rlhf 路径(checkpoints.db 不存在)
3. 两者都缺 → 返 [] 不抛
4. llm_mode='real' 调 model
5. trace_source='checkpoints' 强制主源(无 checkpoint → 返 [])
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. 主源 checkpoints.db
# ---------------------------------------------------------------------------


def test_dream_writes_memory_from_checkpoints_db(tmp_path):
    """🟢Day 4 #D 验收:扫 checkpoints.db 写 memory → 检索命中。

    严格性修复:用真 LangGraph SqliteSaver 写一条 trace(不是手写 SQLite),
    跑 run_dream(trace_source='checkpoints', llm_mode='mock') → ≥1 hit。
    验证 _load_last_checkpoint_trace 适配真 SqliteSaver schema。
    """
    from dream.dream_prototype import run_dream
    from runner.agent_engine import AgentRunner
    from langchain_core.messages import AIMessage

    cp_db = tmp_path / "real_checkpoints.db"

    # 用真 AgentRunner + SqliteSaver 跑一次,写一条真 trace
    class _LLM:
        def __init__(self):
            self._n = 0

        def __call__(self, messages, tools=None):
            self._n += 1
            if self._n == 1:
                # 第一次: 调个 echo tool 让 trace 有内容
                return AIMessage(content="", tool_calls=[
                    {"name": "echo", "args": {"msg": "x"}, "id": "1"}
                ])
            return AIMessage(content="[done]")

    # 注册临时 echo tool
    from pydantic import BaseModel
    from tools.registry import ToolDef, register_tool

    class EchoArgs(BaseModel):
        msg: str

    def _echo_execute(args, ctx):
        return "echo-result"

    register_tool(ToolDef(
        id="echo",
        description="echo back msg",
        schema=EchoArgs,
        execute=_echo_execute,
    ))

    try:
        # factor allowlist 暂没 echo,加进去
        from tools.registry import registry
        runner = AgentRunner(
            group="factor",
            model=_LLM(),
            checkpoint_db=cp_db,
        )
        # 用真 run,触发真 SqliteSaver 写 trace
        runner.run(
            task="dream test",
            skill_name=None,
            system_prompt="x",
            thread_id="dream-real-test",
        )
    finally:
        from tools.registry import registry as global_registry
        global_registry._tools.pop("echo", None)

    # 验证 checkpoints.db 是真 SqliteSaver 格式 + 至少 1 条 trace
    with sqlite3.connect(str(cp_db)) as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t[0] for t in tables}
        assert "checkpoints" in table_names, f"应建 checkpoints 表,got {table_names}"
        cols = conn.execute("PRAGMA table_info(checkpoints)").fetchall()
        col_names = {c[1] for c in cols}
        assert {"thread_id", "checkpoint_ns", "checkpoint_id", "checkpoint"} <= col_names, (
            f"checkpoints 表缺真 SqliteSaver 列,got {col_names}"
        )
        # 真写入了 trace
        rows = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
        assert rows[0] >= 1, f"checkpoints 表应 ≥1 条 trace,got {rows[0]}"

    # 跑 dream,主源从真 SqliteSaver 写的 db 读
    hits = run_dream(
        trace_source="checkpoints",
        db_path=cp_db,
        rlhf_path=tmp_path / "rlhf.jsonl",
        memory_root=tmp_path,
        llm_mode="mock",
    )
    assert len(hits) >= 1, f"dream 写 memory 后应能 search 到,got {len(hits)} hits"
    assert any("Repetitions" in h["snippet"] or "Lessons" in h["snippet"] for h in hits), (
        f"hit 的 snippet 应含 Dream Summary 段,got {hits[0]['snippet'][:80]}"
    )
    # 严格断言:dream summary 来自 mock("Repetitions" 段是 mock 的固定文本)
    assert "calc_risk" in hits[0]["snippet"], (
        f"mock summary 应含 'calc_risk'(mock 的固定 hotspot),got {hits[0]['snippet'][:200]}"
    )


# ---------------------------------------------------------------------------
# 2. fallback rlhf
# ---------------------------------------------------------------------------


def test_dream_falls_back_to_rlhf_when_checkpoints_empty(tmp_path):
    """🟢Day 4 #D 验收:checkpoints.db 不存在 → fallback 到 rlhf_data.jsonl。

    trace_source='auto' 时优先 checkpoints,失败自动用 rlhf。
    """
    from dream.dream_prototype import run_dream

    # checkpoints.db 不存在
    cp_db = tmp_path / "no_such_cp.db"
    # rlhf_data.jsonl 写 1 条 fixture
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps(
            {
                "thread_id": "rlhf-test-thread",
                "state_fingerprint": "abc",
                "action": {"tool_name": "calc_risk", "tool_args": {"scenario": "high_risk"}},
                "observation": {"success": True, "summary": "ok"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    hits = run_dream(
        trace_source="auto",
        db_path=cp_db,
        rlhf_path=rlhf,
        memory_root=tmp_path,
        llm_mode="mock",
    )
    assert len(hits) >= 1, f"fallback 路径应写 memory,got {len(hits)} hits"


# ---------------------------------------------------------------------------
# 3. 两者都缺
# ---------------------------------------------------------------------------


def test_dream_handles_both_missing_gracefully(tmp_path):
    """🟢Day 4 #D 验收:checkpoints.db + rlhf_data.jsonl 都缺 → 返 [] 不抛。
    """
    from dream.dream_prototype import run_dream

    hits = run_dream(
        trace_source="auto",
        db_path=tmp_path / "no_cp.db",
        rlhf_path=tmp_path / "no_rlhf.jsonl",
        memory_root=tmp_path,
        llm_mode="mock",
    )
    assert hits == [], f"两个源都缺应返 [], got {hits}"


# ---------------------------------------------------------------------------
# 4. llm_mode='real' 调 model
# ---------------------------------------------------------------------------


def test_dream_uses_real_llm_when_mode_real(tmp_path):
    """🟢Day 4 #D 验收:llm_mode='real' 时 model 被调 1 次,summary 真来自 model 返回值。

    严格断言:用 sentinel 字符串(不依赖 FTS 解析)直接读 memory body 文件,
    验证 model 返的 "RealLlmSentinel" 三个字段真进 body。
    """
    from dream.dream_prototype import run_dream

    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps(
            {
                "thread_id": "real-llm-test",
                "action": {"tool_name": "calc_risk"},
                "observation": {"success": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    call_count = {"n": 0}

    def fake_model(prompt: str):
        call_count["n"] += 1
        return {
            "repetitions": ["RealLlmSentinel-rep"],
            "lessons": ["RealLlmSentinel-lesson"],
            "hotspots": ["RealLlmSentinel-hot"],
        }

    hits = run_dream(
        trace_source="rlhf",
        rlhf_path=rlhf,
        memory_root=tmp_path,
        llm_mode="real",
        model=fake_model,
    )
    assert call_count["n"] == 1, f"model 应被调 1 次,实际 {call_count['n']}"
    assert len(hits) >= 1
    # 🟢严格断言:不依赖 FTS 解析,直接读 memory body 文件验证 sentinel
    body_path = Path(hits[0]["path"])
    assert body_path.exists(), f"memory body 文件应存在: {body_path}"
    body = body_path.read_text(encoding="utf-8")
    # mock 模式固定的 token(用来确认 real LLM 路径不走 mock fallback)
    for mock_only_token in ["Day 4 stub: 固定返回", "Day2 mock"]:
        assert mock_only_token not in body, (
            f"real LLM 不应含 mock token '{mock_only_token}',body: {body[:200]}"
        )
    # 严格断言:model 返的 3 个 sentinel 字段真在 body 里
    assert "RealLlmSentinel-rep" in body, (
        f"body 应含 model 返的 'RealLlmSentinel-rep',body: {body[:300]}"
    )
    assert "RealLlmSentinel-lesson" in body, (
        f"body 应含 model 返的 'RealLlmSentinel-lesson',body: {body[:300]}"
    )
    assert "RealLlmSentinel-hot" in body, (
        f"body 应含 model 返的 'RealLlmSentinel-hot',body: {body[:300]}"
    )


# ---------------------------------------------------------------------------
# 5. trace_source='checkpoints' 强制主源
# ---------------------------------------------------------------------------


def test_dream_trace_source_checkpoints_strict(tmp_path):
    """🟢Day 4 #D 验收:trace_source='checkpoints' 强制主源,checkpoint 空 → 返 []。

    即便 rlhf 存在,strict checkpoints 模式不会 fallback。
    """
    from dream.dream_prototype import run_dream

    # checkpoints.db 不存在
    cp_db = tmp_path / "no_cp.db"
    # 但 rlhf 存在(strict 模式应该不用)
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps({"thread_id": "strict-test", "action": {}, "observation": {}}) + "\n",
        encoding="utf-8",
    )

    hits = run_dream(
        trace_source="checkpoints",
        db_path=cp_db,
        rlhf_path=rlhf,
        memory_root=tmp_path,
        llm_mode="mock",
    )
    assert hits == [], f"strict checkpoints 模式 + 主源空 应返 [], got {hits}"


# ---------------------------------------------------------------------------
# 6. model 必传校验
# ---------------------------------------------------------------------------


def test_dream_real_mode_requires_model(tmp_path):
    """🟢Day 4 #D 验收:llm_mode='real' + model=None → 抛 ValueError。
    """
    from dream.dream_prototype import run_dream

    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps({"thread_id": "x", "action": {}, "observation": {}}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="model"):
        run_dream(
            trace_source="rlhf",
            rlhf_path=rlhf,
            memory_root=tmp_path,
            llm_mode="real",
            model=None,
        )


# ---------------------------------------------------------------------------
# Day 5 补强：rlhf 聚合（跨多条 trace，而非只读最后一条）
# ---------------------------------------------------------------------------


def test_dream_aggregates_multiple_rlhf_records(tmp_path):
    """Day 5：_load_rlhf_aggregate 应跨多条记录统计 tool 频次 + thread 数。"""
    from dream.dream_prototype import _load_rlhf_aggregate

    rlhf = tmp_path / "rlhf.jsonl"
    lines = [
        {"thread_id": "t1", "group": "risk", "action": {"tool_name": "calc_risk"}},
        {"thread_id": "t1", "group": "risk", "action": {"tool_name": "check_gate"}},
        {"thread_id": "t2", "group": "risk", "action": {"tool_name": "calc_risk"}},
    ]
    rlhf.write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
    )

    agg = _load_rlhf_aggregate(rlhf)
    assert agg is not None
    a = agg["_aggregate"]
    assert a["total_records"] == 3
    assert a["thread_count"] == 2
    assert a["tool_frequency"]["calc_risk"] == 2
    assert "risk" in a["groups"]
    # 向后兼容：仍保留最后一条的 thread_id 字段
    assert agg["thread_id"] == "t2"
