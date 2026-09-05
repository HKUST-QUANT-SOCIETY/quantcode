"""Session-level review — post-hoc label 回填（AG-04 后精简重建版）。

两条回填路径：

1. 人工裁决 ``apply_session_verdict(thread_id, verdict)``:
   session 结束后人工给出 "safe" | "risky"，系统按 risk_score top-N
   回填该 session 中 ``gate_purpose="normal"`` 记录的 label。

2. Judge 裁决 ``apply_judged_session(thread_id, goal, trace)``:
   用 :mod:`runner.judge` 的 LLM judge 评估 goal 达成度，
   按 verdict 写 label —— met=1 / missed=0；
   partial=0.5 不改 label（label 只收 0/1），仅记 reasons 到 notes。

安全约定：RLHF 文件路径一律使用模块常量 :data:`RLHF_PATH`
（``runner.routing.rlhf_logger.RLHF_PATH``），不从参数进入。
"""
from __future__ import annotations

__all__ = ["apply_session_verdict", "apply_judged_session", "reviewer_review_session"]

import json
import os
from typing import Any, Callable

from .rlhf_logger import RLHF_PATH, rewrite_session_records

_VERDICT_LABEL = {
    "met": 1,
    "missed": 0,
    # partial → 0.5：不写 label（label 域只有 0/1），只记 notes；不走本 map
}


# ---------------------------------------------------------------------------
# Reviewer interface (stub — 人工判定 / 未来可注入 LLM)
# ---------------------------------------------------------------------------

def reviewer_review_session(
    thread_id: str,
    rlhf_path: Any = None,
) -> dict[str, Any] | None:
    """会话级 reviewer 接口。

    精简重建：默认返回 None（无人审 ⇒ 走 top-N fallback）。
    保持 AG-04 前既有接口形状（返回值可为 None / 标注 dict），
    支持后续注入 LLM judge 或人工审核面板。

    Args:
        thread_id: 会话 ID。
        rlhf_path: 兼容占位参数；未使用（路径走模块常量）。

    Returns:
        None → reviewer 没空，走 top-N fallback。
        dict → e.g. ``{"mode": "manual", "marked_iterations": [3, 7]}``。
    """
    return None


# ---------------------------------------------------------------------------
# Internal helpers — path is the module-level RLHF_PATH constant only
# ---------------------------------------------------------------------------

def _load_session_records(thread_id: str, path: Any) -> list[dict[str, Any]]:
    """加载 RLHF JSONL 中属于 thread_id 的全部记录（path 恒为模块常量）。"""
    if not path or not path.exists():
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


def _rewrite_session_records(thread_id: str, updated: list[dict[str, Any]], path: Any) -> None:
    """原子重写 RLHF JSONL 中属于 thread_id 的记录。

    ponytail: 实际写入委托给 :func:`rlhf_logger.rewrite_session_records`
    （tempfile.mkstemp 同目录临时文件 + Path.replace，已过安全审计）；
    本模块不再持有任何文件写 sink。
    """
    if path is not RLHF_PATH:
        raise TypeError("path must be the module-level RLHF_PATH constant")
    rewrite_session_records(thread_id, updated)


def _write_marks(
    thread_id: str,
    marked_iterations: list[int],
    mode: str,
    notes: str,
    label: int = 1,
) -> dict[str, Any]:
    """把 marked iterations 连同 label 回填到该 session 的 normal 记录（原子写）。"""
    all_records = _load_session_records(thread_id, RLHF_PATH)
    marked = set(marked_iterations)
    for r in all_records:
        if r.get("gate_purpose") != "normal":
            continue
        iteration = (r.get("metadata") or {}).get("iteration")
        if iteration in marked:
            r["label"] = label
            r["human_decision"] = "abort"  # 事后标注补写
        if notes:
            r["notes"] = notes
    _rewrite_session_records(thread_id, all_records, RLHF_PATH)
    return {
        "thread_id": thread_id,
        "mode": mode,
        "marked_iterations": sorted(marked),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 人工裁决路径
# ---------------------------------------------------------------------------

def apply_session_verdict(thread_id: str, verdict: str, *, top_n: int = 1) -> dict[str, Any]:
    """FINISH 后人工回填 label。

    Args:
        thread_id: 会话 ID。
        verdict: "safe" | "risky"。
        top_n: reviewer（见 :func:`reviewer_review_session`）返回 None 时的
            自动回填条数（按 risk_score 降序取前 N）。

    Returns:
        分诊报告 dict（mode: auto / manual / none）。
    """
    risk_continues = [
        r for r in _load_session_records(thread_id, RLHF_PATH)
        if r.get("gate_purpose") == "normal" and r.get("risk_score") is not None
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

    reviewer_marks = reviewer_review_session(thread_id)
    if reviewer_marks is not None:  # 人工精确标注
        marked = [int(i) for i in reviewer_marks.get("marked_iterations", [])]
        report["mode"] = "manual"
    else:  # reviewer 没空 → risk_score top-N fallback
        risk_continues.sort(key=lambda r: r.get("risk_score") or 0, reverse=True)
        marked = [(r.get("metadata") or {}).get("iteration") for r in risk_continues[:top_n]]
        marked = [m for m in marked if m is not None]
        report["mode"] = "auto"

    _write_marks(thread_id, marked, report["mode"], notes="")
    report["marked_iterations"] = marked
    return report


# ---------------------------------------------------------------------------
# Judge 裁决路径（PRD §4.4 P2 Goal + Judge）
# ---------------------------------------------------------------------------

def apply_judged_session(
    thread_id: str,
    goal: str,
    trace: list[dict[str, Any]],
    *,
    llm: Callable[..., Any] | None = None,
    top_n: int = 1,
) -> dict[str, Any]:
    """调 runner.judge.judge_run 评估 → 按 verdict 写 label。

    - met    → 同人工 "risky" 语义反转前的口径：目标达成 ⇒ 兜底 continue 无误 ⇒ label=1
    - missed → label=0
    - partial → label 不写（0.5 落不进 0/1 域），只记 notes
    - unevaluated → 不改文件，报告中如实反映

    Returns:
        {"thread_id", "verdict", "reasons", "marked_iterations", "mode", "n_risk_continues"}
    """
    from runner.judge import judge_run, summarize_run

    summary = summarize_run(trace)
    judged = judge_run(goal, summary, llm=llm)
    verdict = judged["verdict"]
    reasons = judged.get("reasons", [])
    notes = f"judge:{verdict}: " + "; ".join(reasons[:5]) if reasons else f"judge:{verdict}"

    report: dict[str, Any] = {
        "thread_id": thread_id,
        "verdict": verdict,
        "reasons": reasons,
        "mode": "judge",
        "marked_iterations": [],
        "n_risk_continues": 0,
    }

    if verdict == "unevaluated":
        # 诚实降级：不碰 RLHF 文件
        report["mode"] = "unevaluated"
        return report

    risk_continues = [
        r for r in _load_session_records(thread_id, RLHF_PATH)
        if r.get("gate_purpose") == "normal" and r.get("risk_score") is not None
    ]
    report["n_risk_continues"] = len(risk_continues)

    if verdict == "partial":
        # partial（0.5）：不写 label，只把 judge 原因记进 notes
        _write_marks(thread_id, [], "judge", notes=notes)
        report["marked_iterations"] = []
        return report

    # met / missed：选 top 迭代回填 label（沿用 top-N 语义）
    if risk_continues:
        risk_continues.sort(key=lambda r: r.get("risk_score") or 0, reverse=True)
        marked = [(r.get("metadata") or {}).get("iteration") for r in risk_continues[:top_n]]
        marked = [int(m) for m in marked if m is not None]
    else:
        marked = []
    _write_marks(thread_id, marked, "judge", notes=notes, label=_VERDICT_LABEL[verdict])
    report["marked_iterations"] = marked
    return report