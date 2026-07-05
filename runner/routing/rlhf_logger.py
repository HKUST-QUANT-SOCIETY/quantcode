"""
RLHF data logger — append one JSON line per tool call for future training.

Output path: .quantcode/rlhf_data.jsonl (relative to quantcode repo root).
"""
from __future__ import annotations

import json
# import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Resolve repo root (assumes this file lives in runner/routing/)
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Walk up from this file until we find .git or pyproject.toml."""
    here = Path(__file__).resolve().parent
    for _ in range(6):
        if (here / ".git").exists() or (here / "pyproject.toml").exists():
            return here
        here = here.parent
    # Fallback: assume cwd is the repo root
    return Path.cwd()


RLHF_PATH = _repo_root() / ".quantcode" / "rlhf_data.jsonl"


# ---------------------------------------------------------------------------
# Reward constants (Plan §1.5)
# ---------------------------------------------------------------------------

REWARD = {
    "tool_success":           +1,
    "tool_failure":           -1,
    "human_gate_approved":   +10,
    "human_gate_rejected":    -5,
    "loop_detected":         -10,
    "max_iterations_exceeded": -10,
    "task_finished":          +5,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_rlhf_entry(
    entry: dict[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    """
    Append one JSON line to the RLHF data file.

    Returns the absolute path written to.
    """
    target = path or RLHF_PATH
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
    reward_key: str = "tool_success",
    iteration: int = 0,
    route: str = "continue",
) -> dict[str, Any]:
    """
    Build a standard RLHF entry dict.

    `reward_key` picks from REWARD constants. Unrecognized keys → 0.
    """
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
        "reward": REWARD.get(reward_key, 0),
        "metadata": {
            "iteration": iteration,
            "route": route,
        },
    }
