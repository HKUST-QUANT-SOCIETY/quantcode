"""
State fingerprint — compute a deterministic hash of the business-significant
portion of an Agent state, ignoring volatile fields like timestamps.

Used by guards.py to detect repeated-state loops (same hash appearing
repeatedly means the Agent isn't making progress).

来源：cherry-pick from PR #16 (shutong-114, gaolei/day3-routing-guards)。
由 leader 决定从源头避开 messages 累积导致指纹永不重复的问题（白名单
实现只 hash 5 个特定业务字段，不 hash 整个 state 再黑名单过滤）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# ---------------------------------------------------------------------------
# Fields included in the fingerprint (business-meaningful state)
# ---------------------------------------------------------------------------
FINGERPRINT_FIELDS = {
    "current_step",
    "last_tool",
    "tool_args",
    "output_data",
    "errors",
}

# 注：PR #16 原版还导出了一个 EXCLUDED_FIELDS = {"timestamp", "trace_id",
# "iteration_count"}，但 compute_state_fingerprint 只遍历 FINGERPRINT_FIELDS，
# 这些 excluded key 永远不会被引用 —— 是死代码。cherry-pick 后删掉以避免误导
# （若 #16 后续要复用 excluded 语义，再加回来，但目前对本仓库无意义）。


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_state_fingerprint(state: dict[str, Any]) -> str:
    """
    Compute a SHA-256 fingerprint from the business-significant slice of
    `state`.  Two states that differ only in volatile fields (timestamp,
    trace_id, iteration_count) produce the same fingerprint.
    """
    normalized: dict[str, Any] = {}
    for field in sorted(FINGERPRINT_FIELDS):
        normalized[field] = state.get(field)

    payload = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "FINGERPRINT_FIELDS",
    "compute_state_fingerprint",
]
