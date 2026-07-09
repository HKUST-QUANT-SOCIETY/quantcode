"""Dream IDE 触发入口 — Day 5 尹一帆。

封装 ``run_dream()`` 单入口,提供事件流(``dream_events.jsonl``)供 IDE 消费。

事件格式::

    {
        "event": "dream_started" | "dream_completed" | "dream_failed",
        "timestamp": "2026-07-09T19:55:00.123Z",
        "payload": {
            "thread_id": "...",
            "hits_count": 3,
            "duration_ms": 123,
            "error": "..."  # 仅 dream_failed
        }
    }

设计要点:
- 不修改 ``dream_prototype.run_dream()``,只包装调用 + 加事件
- event_sink 可为 None(仅返 inline)/ Path(append JSONL)/ callable(直接调)
- 后台调度器与 CLI 都通过此函数触发,避免逻辑分散
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _emit_event(
    event_sink: Path | Callable[[dict], None] | None,
    events_inline: list[dict] | None,
    event: dict,
) -> None:
    """统一事件发送:写到 Path / 调 callable / 始终保留 inline 副本。

    inline 副本让调用方即便传了 Path 也能从返回值读事件,
    不需要再读盘。
    """
    # 始终保留 inline 副本
    if events_inline is not None:
        events_inline.append(event)
    if event_sink is None:
        return
    if callable(event_sink):
        event_sink(event)
        return
    # Path: append JSONL
    sink_path = Path(event_sink)
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    with sink_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def trigger_dream(
    *,
    rlhf_path: str | Path = ".quantcode/rlhf_data.jsonl",
    memory_root: str | Path = ".quantcode",
    event_sink: Path | Callable[[dict], None] | None = None,
    llm_mode: str = "auto",
    model: Callable | None = None,
) -> dict:
    """Dream IDE 触发入口。

    Args:
        rlhf_path: RLHF 数据文件路径
        memory_root: MemoryService 写入根目录
        event_sink: 事件流接收方 — None(返 inline)/ Path(写 JSONL)/ callable
        llm_mode: 透传给 ``run_dream``
        model: 透传给 ``run_dream``(llm_mode='real' 时必传)

    Returns:
        dict 含 ``hits`` (与 ``run_dream`` 一致) + ``events`` (事件列表)
    """
    from dream.dream_prototype import run_dream  # 延迟 import 避免循环

    events_inline: list[dict] = []
    started_at = time.time()
    started_ts = datetime.now(timezone.utc).isoformat()

    _emit_event(event_sink, events_inline, {
        "event": "dream_started",
        "timestamp": started_ts,
        "payload": {"rlhf_path": str(rlhf_path)},
    })

    try:
        hits = run_dream(
            trace_source="auto",
            rlhf_path=rlhf_path,
            memory_root=memory_root,
            llm_mode=llm_mode,
            model=model,
        )
        duration_ms = int((time.time() - started_at) * 1000)
        hits_list = [
            {"path": h["path"], "scope": h["scope"], "snippet": h["snippet"]}
            for h in hits
        ]
        # thread_id 从 path 推(dream/<thread_id>.md)
        thread_id = "unknown"
        if hits_list:
            filename = hits_list[0]["path"].rsplit("/", 1)[-1]
            if filename.endswith(".md"):
                thread_id = filename[:-3]
        _emit_event(event_sink, events_inline, {
            "event": "dream_completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "thread_id": thread_id,
                "hits_count": len(hits),
                "duration_ms": duration_ms,
            },
        })
        return {
            "hits": hits_list,
            "events": events_inline,
        }
    except Exception as e:
        duration_ms = int((time.time() - started_at) * 1000)
        _emit_event(event_sink, events_inline, {
            "event": "dream_failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "error": f"{type(e).__name__}: {e}",
                "duration_ms": duration_ms,
            },
        })
        # 事件已发送,异常仍向上抛(让调度器知道失败)
        raise


__all__ = ["trigger_dream"]