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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._utils import _repo_root

# Import thresholds from risk_stub to stay in sync
from tools.risk_stub import VAR_99_LIMIT, MAX_DRAWDOWN_LIMIT, POSITION_LIMIT_LIMIT


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

    阈值从 ``tools/risk_stub.py`` import，自动与 router 同步。
    返回 None 表示无风险数据。
    """
    if not risk_features:
        return None
    ratios = [
        risk_features.get("tail_risk_var_99", 0) / VAR_99_LIMIT,
        risk_features.get("max_drawdown", 0) / MAX_DRAWDOWN_LIMIT,
        risk_features.get("position_limit", 0) / POSITION_LIMIT_LIMIT,
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
      - continue  + 事后 session_verdict      → 由 apply_session_verdict 回填
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
