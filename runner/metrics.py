"""Run metrics — best-effort JSONL 运行记录（ponytail 最小闭环）。

写：``runner/agent_engine.py`` 的 run/stream/resume 完成钩子在 finally 段调
``record_run``，追加一行 JSON 到 `.quantcode/metrics.jsonl`（写失败静默）。

读：``quantcode/mcp_server.py`` 注册只读工具 ``list_runs``，内部调
``read_recent`` + ``aggregate`` 返回最近运行与汇总指标。

设计要点（ponytail）：
- 纯标准库（json/time/pathlib），无新依赖。
- 所有公开函数 best-effort：任何 I/O / 解析失败都静默，绝不影响主流程。
- context_chars 用 ``estimate_context_chars`` 对 trace 文本粗估（字符数）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
METRICS_PATH = PROJECT_ROOT / ".quantcode" / "metrics.jsonl"


def estimate_context_chars(trace_events: list[dict] | None) -> int | None:
    """从 trace 事件粗估上下文体积（字符数）；无事件返回 None。

    把每个事件的 data 系列化后数字符——够做"上下文膨胀"趋势观察，不做精确 token。
    """
    if not trace_events:
        return None
    total = 0
    for ev in trace_events:
        if not isinstance(ev, dict):
            continue
        data = ev.get("data")
        if isinstance(data, dict):
            for value in data.values():
                total += len(str(value))
        elif data is not None:
            total += len(str(data))
    return total


def record_run(
    group: str,
    flow: str,
    thread_id: str,
    started_at: float | None,
    ended_at: float | None,
    status: str,
    error: str | None = None,
    context_chars: int | None = None,
    trace_events: list[dict] | None = None,
) -> None:
    """追加一行 run 记录到 `.quantcode/metrics.jsonl`（best-effort，失败静默）。"""
    try:
        events = trace_events if isinstance(trace_events, list) else []
        duration: float | None = None
        if isinstance(started_at, (int, float)) and isinstance(ended_at, (int, float)):
            duration = round(float(ended_at) - float(started_at), 3)
        entry = {
            "ts": round(time.time(), 3),
            "group": str(group or ""),
            "flow": str(flow or ""),
            "thread_id": str(thread_id or ""),
            "duration_s": duration,
            "status": str(status or ""),
            "error": error,
            "tool_calls": sum(
                1 for e in events if isinstance(e, dict) and e.get("type") == "tool_call"
            ),
            "llm_thoughts": sum(
                1 for e in events if isinstance(e, dict) and e.get("type") == "llm_thought"
            ),
            "context_chars": (
                context_chars if context_chars is not None else estimate_context_chars(events)
            ),
        }
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with METRICS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:  # ponytail: metrics 是 best-effort，任何失败都静默
        pass


def read_recent(limit: int = 50) -> list[dict]:
    """读最近 ``limit`` 条 run 记录（按文件顺序，旧→新）；损坏行静默跳过。"""
    if limit <= 0:
        return []
    try:
        with METRICS_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def aggregate(window: int = 20) -> dict[str, Any]:
    """对最近 ``window`` 条 run 记录做汇总。

    返回 ``{runs, success_rate, avg_duration_s, error_rate, by_group}``；
    ``by_group[g] = {runs, success, errors, avg_duration_s}``。空窗口全零。
    """
    runs = read_recent(window)
    total = len(runs)
    if total == 0:
        return {
            "runs": 0,
            "success_rate": 0.0,
            "avg_duration_s": 0.0,
            "error_rate": 0.0,
            "by_group": {},
        }

    completed = sum(1 for r in runs if r.get("status") == "completed")
    errored = sum(1 for r in runs if r.get("status") == "error")
    durations = [
        float(r["duration_s"])
        for r in runs
        if isinstance(r.get("duration_s"), (int, float))
    ]

    by_group: dict[str, dict[str, Any]] = {}
    for r in runs:
        g = str(r.get("group") or "unknown")
        slot = by_group.setdefault(g, {"runs": 0, "success": 0, "errors": 0, "_dur": []})
        slot["runs"] += 1
        if r.get("status") == "completed":
            slot["success"] += 1
        if r.get("status") == "error":
            slot["errors"] += 1
        if isinstance(r.get("duration_s"), (int, float)):
            slot["_dur"].append(float(r["duration_s"]))

    for slot in by_group.values():
        durs = slot.pop("_dur")
        slot["avg_duration_s"] = round(sum(durs) / len(durs), 3) if durs else 0.0

    return {
        "runs": total,
        "success_rate": round(completed / total, 3),
        "avg_duration_s": round(sum(durations) / len(durations), 3) if durations else 0.0,
        "error_rate": round(errored / total, 3),
        "by_group": by_group,
    }


__all__ = ["METRICS_PATH", "record_run", "read_recent", "aggregate", "estimate_context_chars"]