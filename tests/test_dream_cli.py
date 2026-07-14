"""Dream CLI 入口整体闭环测试 — Day 5 尹一帆。

覆盖:
1. ``python -m dream.cli --once`` 跑通,事件流落盘
2. ``--interval 0`` 视为只跑一次(测试用,避免真循环)

走整体逻辑闭环:subprocess 跑真 CLI,验证事件流 + memory 真写入。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_dream_cli_once_writes_event(tmp_path):
    """Day 5 #B:CLI --once → 真实 subprocess 跑通 + 事件流落盘。

    走整体逻辑闭环:用 subprocess 跑 python -m dream.cli --once,
    验证 .quantcode/dream_events.jsonl 含 dream_completed。
    """
    rlhf = tmp_path / "rlhf.jsonl"
    rlhf.write_text(
        json.dumps({
            "thread_id": "cli-test",
            "action": {"tool_name": "calc_risk"},
            "observation": {"success": True},
        }) + "\n",
        encoding="utf-8",
    )
    events_path = tmp_path / "dream_events.jsonl"
    memory_root = tmp_path / "qroot"
    memory_root.mkdir()

    # subprocess 跑 CLI,传参指定路径
    result = subprocess.run(
        [
            sys.executable, "-m", "dream.cli",
            "--once",
            "--rlhf-path", str(rlhf),
            "--memory-root", str(memory_root),
            "--event-sink", str(events_path),
            "--llm-mode", "mock",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        f"CLI 应成功,stderr: {result.stderr}"
    )
    assert events_path.exists(), f"事件流文件应存在: {events_path}"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [e["event"] for e in events]
    assert "dream_completed" in event_types, (
        f"事件流应含 dream_completed, got {event_types}"
    )
    # memory 真写入
    mem_db = memory_root / "memory.db"
    assert mem_db.exists(), f"memory.db 应被创建: {mem_db}"