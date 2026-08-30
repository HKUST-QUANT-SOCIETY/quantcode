"""
RLHF data logger — append one JSON line per decision point for future training.

Output path: .quantcode/rlhf_data.jsonl (relative to quantcode repo root).

字段设计（俞高磊 Day 5 重构）:
  - system_decision : 路由决策原始值（human_gate/continue/finish/abort_loop/abort_max_iterations）
  - human_decision  : "proceed" | "abort" | ""（空=无需人审）
  - gate_purpose    : "risk" | "loop" | "max_iter" | "normal" | ""
  - label           : 0 | 1 | None（仅 gate_purpose="risk" 时有值，1=该拦）
  - risk_score      : 0-1 综合风险评分（事后追溯用）
  - risk_features   : 7 维风险特征向量
  - checkpoint_id   : SqliteSaver checkpoint 句柄（兜底回溯）
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._utils import _repo_root
from schemas.risk_profile import RiskThresholds

# 阈值定义权归 schemas.risk_profile.RiskThresholds（单一事实来源，与 router 同步）。
_THRESHOLDS = RiskThresholds()


# ---------------------------------------------------------------------------
# RLHF output path
# ---------------------------------------------------------------------------

RLHF_PATH = _repo_root() / ".quantcode" / "rlhf_data.jsonl"


# ---------------------------------------------------------------------------
# Gate purpose mapping
# ---------------------------------------------------------------------------

_GATE_PURPOSE_MAP: dict[str, str] = {
    "human_gate":            "risk",
    "abort_loop":            "loop",
    "abort_max_iterations":  "max_iter",
    "continue":              "normal",
    "finish":                "normal",
}


# ---------------------------------------------------------------------------
# Risk score (rule-based, threshold-normalized)
# ---------------------------------------------------------------------------

def _compute_risk_score(risk_features: dict[str, Any] | None) -> float | None:
    """综合风险评分，0-1，越高越危险。

    阈值取自 ``schemas.risk_profile.RiskThresholds``，自动与 router 同步。
    返回 None 表示无风险数据。
    """
    if not risk_features:
        return None
    ratios = [
        risk_features.get("tail_risk_var_99", 0) / _THRESHOLDS.tail_risk_var_99,
        risk_features.get("max_drawdown", 0) / _THRESHOLDS.max_drawdown,
        risk_features.get("position_limit", 0) / _THRESHOLDS.position_limit_usage,
        risk_features.get("volatility", 0) / 0.25,
    ]
    # Guard NaN and negative values
    cleaned = [0.0 if (math.isnan(r) or r < 0) else r for r in ratios]
    return round(max(cleaned), 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_rlhf_entry(
    entry: dict[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    """Append one JSON line to the RLHF data file.

    Returns the absolute path written to.
    """
    target = (path or RLHF_PATH).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return target


def make_rlhf_entry(
    *,
    thread_id: str = "",
    group: str = "",
    state_fingerprint: str = "",
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
    success: bool = True,
    summary: str = "",
    iteration: int = 0,
    # ── 核心决策字段 ──
    system_decision: str = "",        # RouteDecision 原始值
    human_decision: str = "",         # "proceed" | "abort" | ""
    risk_features: dict[str, Any] | None = None,
    # ── 兜底 ──
    checkpoint_id: str = "",
) -> dict[str, Any]:
    """Build a standard RLHF entry dict.

    label 推导规则（仅 gate_purpose="risk"）:
      - human_gate + human_decision="abort"  → label=1  (gate_correct: 系统拦对了)
      - human_gate + human_decision="proceed"→ label=0  (gate_false_positive: 误报)
      - continue  + 事后 session_verdict      → 事后人工回填（session_review 已移除）
    """
    # ── gate_purpose ──
    gate_purpose = _GATE_PURPOSE_MAP.get(system_decision, "")

    # ── risk_score ──
    risk_score = _compute_risk_score(risk_features)

    # ── label（仅 risk gate 即时反馈）──
    label: int | None = None
    if gate_purpose == "risk" and human_decision:
        # abort = 人同意系统拦截 = 该拦
        # proceed = 人放行 = 系统误报
        label = 1 if human_decision == "abort" else 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thread_id": thread_id,
        "group": group,
        "state_fingerprint": state_fingerprint,
        "action": {
            "tool_name": tool_name,
            "tool_args": tool_args or {},
        },
        "observation": {
            "success": success,
            "summary": summary,
        },
        "system_decision": system_decision,
        "human_decision": human_decision,
        "gate_purpose": gate_purpose,
        "label": label,
        "risk_score": risk_score,
        "risk_features": risk_features or {},
        "checkpoint_id": checkpoint_id,
        "metadata": {
            "iteration": iteration,
        },
    }


__all__ = [
    "RLHF_PATH",
    "log_rlhf_entry",
    "make_rlhf_entry",
    "load_rlhf_dataset",
]


def load_rlhf_dataset(
    rlhf_path: str | Path,
) -> list[dict[str, Any]]:
    """Load labeled training data from an RLHF JSONL log file.

    Only records with ``gate_purpose="risk"`` and a non-None ``label``
    and non-empty ``risk_features`` are included.

    Returns a list of ``{"risk_features": dict, "label": int}`` dicts.
    """
    target = Path(rlhf_path).resolve()
    if not target.exists():
        raise FileNotFoundError(f"RLHF data file not found: {target}")

    dataset: list[dict[str, Any]] = []
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if record.get("gate_purpose") != "risk":
                continue
            label = record.get("label")
            if label is None:
                continue
            risk_features = (
                record.get("risk_features")
                or {}
            )
            if not risk_features:
                continue

            dataset.append({"risk_features": risk_features, "label": int(label)})

    return dataset


def rewrite_session_records(
    thread_id: str,
    updated: list[dict[str, Any]],
) -> None:
    """原孔回填该 thread 的记录：读旧内容 → 写同目录临时文件 → Path.replace。

    写路径恒为本模块常量 :data:`RLHF_PATH`；临时文件由 tempfile 在
    RLHF_PATH 同目录创建（文件名系统生成、无路径成分），目标路径不来自
    任何调用方输入（Mimosa L3 路径穿越守卫）。
    """
    import tempfile

    keep_lines: list[str] = []
    if RLHF_PATH.exists():
        with open(RLHF_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    keep_lines.append(line)
                    continue
                if record.get("thread_id") == thread_id:
                    continue
                keep_lines.append(line)
    for record in updated:
        keep_lines.append(json.dumps(record, ensure_ascii=False))

    fd, tmp_name = tempfile.mkstemp(
        prefix=RLHF_PATH.name + ".tmp.", dir=str(RLHF_PATH.parent), suffix=".jsonl"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in keep_lines))
        tmp.replace(RLHF_PATH)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
