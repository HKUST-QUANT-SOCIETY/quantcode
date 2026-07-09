"""Dream 后台调度器整体闭环测试 — Day 5 尹一帆。

覆盖:
1. start() 后调度器自动触发 trigger_dream
2. stop() 优雅停机
3. 多次触发产生多个事件

不依赖 IDE 实现 —— 只验证调度器自身行为。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from dream.scheduler import DreamScheduler


@pytest.fixture
def memory_service_with_close():
    """Day 4 MemoryService 无 close(),Windows 上 SQLite 句柄泄漏。"""
    from runner.memory import service as svc_mod

    if not hasattr(svc_mod.MemoryService, "close"):
        def _close(self):
            self._closed = True
        svc_mod.MemoryService.close = _close
    return svc_mod.MemoryService


def test_scheduler_triggers_dream_multiple_times(tmp_path, memory_service_with_close):
    """Day 5 #B:调度器每 0.1 秒触发一次,0.5 秒后 stop → ≥3 次触发。

    走整体逻辑闭环:起调度器 → 等真实时间 → stop → 验证事件流真实写入。
    """
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps({
            "thread_id": "scheduler-test",
            "action": {"tool_name": "calc_risk"},
            "observation": {"success": True},
        }) + "\n",
        encoding="utf-8",
    )
    events_path = tmp_path / "events.jsonl"
    memory_root = tmp_path / "qroot"
    memory_root.mkdir()

    scheduler = DreamScheduler(
        interval=0.1,
        rlhf_path=rlhf,
        memory_root=memory_root,
        event_sink=events_path,
        llm_mode="mock",
    )
    scheduler.start()
    time.sleep(0.5)  # 跑 ~5 次
    scheduler.stop()

    assert events_path.exists(), f"事件流文件应存在: {events_path}"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completed = sum(1 for e in events if e["event"] == "dream_completed")
    assert completed >= 3, f"应触发 ≥3 次,实际 {completed} 次"


def test_scheduler_stop_is_idempotent(tmp_path, memory_service_with_close):
    """Day 5 #B:stop() 多次调用安全(幂等)。

    验证优雅停机不会抛异常。
    """
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text("{}", encoding="utf-8")
    events_path = tmp_path / "events.jsonl"
    memory_root = tmp_path / "qroot"
    memory_root.mkdir()

    scheduler = DreamScheduler(
        interval=1.0,
        rlhf_path=rlhf,
        memory_root=memory_root,
        event_sink=events_path,
        llm_mode="mock",
    )
    scheduler.start()
    time.sleep(0.05)
    scheduler.stop()
    scheduler.stop()  # 第二次 stop 不应抛异常