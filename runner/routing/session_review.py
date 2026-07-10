"""
Session-level review — post-hoc labeling of risk continue decisions.

After a session FINISHes, a human reviewer (or Judge model) can mark the
entire session as "safe" or "risky".  If "risky", the system pinpoints
which individual ``continue`` steps were likely gate misses.

Workflow:
  1. FINISH → apply_session_verdict(thread_id, verdict)
  2. reviewer_review_session() is called to get precise iteration marks
     - Returns None  → reviewer too busy; fall back to top-N by risk_score
     - Returns [3,7] → mark iterations 3 and 7 as gate_miss (label=1)
     - Returns []    → reviewer looked, all fine (no change)
  3. Labels are written back into the RLHF JSONL file

Usage::

    from runner.routing.session_review import apply_session_verdict

    apply_session_verdict("model-abc123", "risky", top_n=2)
"""
from __future__ import annotations

__all__ = ["apply_session_verdict", "reviewer_review_session"]

import json
import os
from pathlib import Path
from typing import Any

from .rlhf_logger import RLHF_PATH


# ---------------------------------------------------------------------------
# Reviewer interface (stub — production replaces this)
# ---------------------------------------------------------------------------

def reviewer_review_session(
    thread_id: str,
    records: list[dict[str, Any]],
) -> list[int] | None:
    """Reviewer 精确标注接口。

    Args:
        thread_id: 会话 ID
        records: 该 session 所有 gate_purpose="normal" 且有 risk_score 的记录，
                 按 iteration 排序，每条含:
                   - metadata.iteration
                   - risk_score
                   - risk_features
                   - action.tool_name

    Returns:
        None        → 没空审，走 top-N fallback
        [3, 7]      → 明确标记 iteration 3 和 7 为 gate_miss
        []          → 审了但觉得都没问题（等价于 safe）
    """
    # ── Stub: 模拟"没空" ──
    return None


# ---------------------------------------------------------------------------
# Session verdict application
# ---------------------------------------------------------------------------

def apply_session_verdict(
    thread_id: str,
    verdict: str,
    *,
    rlhf_path: str | Path = RLHF_PATH,
    top_n: int = 1,
) -> dict[str, Any]:
    """FINISH 后人审回填 label。

    Args:
        thread_id: 会话 ID
        verdict: "safe" | "risky"
        rlhf_path: RLHF 日志路径
        top_n: reviewer=None 时的自动标记条数

    Returns:
        {
            "thread_id": "...",
            "verdict": "risky",
            "mode": "auto" | "manual" | "none",
            "marked_iterations": [3, 7],
            "n_risk_continues": 12,
        }
    """
    target = Path(rlhf_path).resolve()

    # 1. 加载该 session 所有记录
    all_records = _load_session_records(thread_id, target)

    # 2. 筛选 risk continue（未即时 gate 但有风险信息的步骤）
    risk_continues = [
        r for r in all_records
        if (r.get("gate_purpose") == "normal"
            and r.get("risk_score") is not None)
    ]

    report: dict[str, Any] = {
        "thread_id": thread_id,
        "verdict": verdict,
        "mode": "none",
        "marked_iterations": [],
        "n_risk_continues": len(risk_continues),
    }

    if verdict == "safe" or not risk_continues:
        return report

    # 3. 问 reviewer
    reviewer_marks = reviewer_review_session(thread_id, risk_continues)

    # 4. 确定要标记的 iteration
    if reviewer_marks is not None:
        # reviewer 有空，精确标注
        marked = reviewer_marks
        report["mode"] = "manual"
    else:
        # reviewer 没空，top-N fallback
        risk_continues.sort(key=lambda r: r.get("risk_score") or 0, reverse=True)
        marked = [r["metadata"]["iteration"] for r in risk_continues[:top_n]]
        report["mode"] = "auto"

    # 5. 写回 label
    for r in all_records:
        if (r.get("gate_purpose") == "normal"
                and r["metadata"].get("iteration") in marked):
            r["label"] = 1
            r["human_decision"] = "abort"   # 事后标注补写

    _rewrite_session_records(thread_id, all_records, target)
    report["marked_iterations"] = marked
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_session_records(
    thread_id: str,
    path: Path,
) -> list[dict[str, Any]]:
    """Load all records for a given thread_id from the RLHF JSONL file."""
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("thread_id") == thread_id:
                records.append(record)
    return records


def _rewrite_session_records(
    thread_id: str,
    updated_records: list[dict[str, Any]],
    path: Path,
) -> None:
    """Rewrite the RLHF JSONL file atomically with updated records for one session.

    Uses temp file + os.replace to prevent data loss from crashes or
    concurrent writes (os.replace is atomic on all platforms).
    """
    # Read all lines not belonging to this session
    other_lines: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                other_lines.append(line)
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                other_lines.append(line)
                continue
            if record.get("thread_id") == thread_id:
                continue
            other_lines.append(line)

    # Write to temp file, then atomically replace
    tmp = Path(str(path) + ".tmp." + os.urandom(4).hex())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for line in other_lines:
                f.write(line)
            for record in updated_records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
