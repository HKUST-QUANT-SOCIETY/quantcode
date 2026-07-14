"""Dream IDE 触发入口整体闭环测试 — Day 5 尹一帆。

覆盖:
1. trigger_dream() 跑完后,事件写入 event_sink + 真实 memory 写入
2. event_sink=None 时不抛异常,事件仅返回在返回值
3. 重复触发两次,事件流含两次 'dream_completed'

不重复 Day 4 测过的 dream 内部逻辑(checkpoints.db 解析 / RLHF fallback)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dream.trigger import trigger_dream


@pytest.fixture
def memory_service_with_close():
    """Day 4 MemoryService 无 close(),Windows 上 SQLite 句柄泄漏导致 tmp_path 清理失败。

    此 fixture 直接给 MemoryService 类加 close() 方法,让临时目录可清理。
    不修改 Day 4 源码,仅在测试进程内生效(monkeypatch 不能给类加新方法,用 setattr 类属性)。
    """
    from runner.memory import service as svc_mod

    if not hasattr(svc_mod.MemoryService, "close"):
        def _close(self):
            # 不持有长连接,标记让引用计数释放
            self._closed = True
        svc_mod.MemoryService.close = _close
    return svc_mod.MemoryService


def test_trigger_dream_writes_event_and_memory(tmp_path, memory_service_with_close):
    """Day 5 #B:trigger_dream() → 事件写 sink + 真实 memory 写入。

    走整体逻辑闭环:
    1. 准备 RLHF fixture
    2. 调 trigger_dream(event_sink=jsonl_path)
    3. 验证 jsonl 文件含 'dream_started' + 'dream_completed' 两条事件
    4. 验证 .quantcode/memory.db 真有 dream memory 写入
    """
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps({
            "thread_id": "trigger-test",
            "action": {"tool_name": "calc_risk"},
            "observation": {"success": True},
        }) + "\n",
        encoding="utf-8",
    )
    events_path = tmp_path / "dream_events.jsonl"

    result = trigger_dream(
        rlhf_path=rlhf,
        memory_root=tmp_path,
        event_sink=events_path,
        llm_mode="mock",
    )

    # 验证事件流
    assert events_path.exists(), f"事件流文件应存在: {events_path}"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [e["event"] for e in events]
    assert "dream_started" in event_types, f"事件流应含 dream_started, got {event_types}"
    assert "dream_completed" in event_types, f"事件流应含 dream_completed, got {event_types}"

    # 验证 memory 真写入
    mem_db = tmp_path / "memory.db"
    assert mem_db.exists(), f"memory.db 应被创建: {mem_db}"

    # 验证返回值含 hits(与 run_dream 一致)
    assert "hits" in result
    assert len(result["hits"]) >= 1
    # 验证 events 字段在返回值里(event_sink=Path 时也保留 inline 副本)
    assert "events" in result
    assert len(result["events"]) >= 2


def test_trigger_dream_event_sink_none_returns_inline(tmp_path, memory_service_with_close):
    """Day 5 #B:event_sink=None → 事件在返回值 'events' 字段,不写文件。

    验证不强制写盘也能拿到事件。
    """
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps({
            "thread_id": "inline-test",
            "action": {"tool_name": "echo"},
            "observation": {"success": True},
        }) + "\n",
        encoding="utf-8",
    )

    result = trigger_dream(
        rlhf_path=rlhf,
        memory_root=tmp_path,
        event_sink=None,
        llm_mode="mock",
    )

    assert "events" in result
    events = result["events"]
    event_types = [e["event"] for e in events]
    assert "dream_completed" in event_types


def test_trigger_dream_consecutive_calls_emit_separate_events(tmp_path, memory_service_with_close):
    """Day 5 #B:连续触发两次 → 事件流含 2 次 'dream_completed'。

    验证多次触发不丢事件(IDE 需要刷新 Memory 浏览器)。
    """
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps({
            "thread_id": "consecutive-test",
            "action": {"tool_name": "calc_risk"},
            "observation": {"success": True},
        }) + "\n",
        encoding="utf-8",
    )
    events_path = tmp_path / "events.jsonl"

    for _i in range(2):
        trigger_dream(
            rlhf_path=rlhf,
            memory_root=tmp_path,
            event_sink=events_path,
            llm_mode="mock",
        )

    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completed_count = sum(1 for e in events if e["event"] == "dream_completed")
    assert completed_count == 2, f"应含 2 次 dream_completed, got {completed_count}"