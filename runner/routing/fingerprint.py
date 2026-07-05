"""
State fingerprint — compute a deterministic hash of the business-significant
portion of an Agent state, ignoring volatile fields like timestamps.

Used by guards.py to detect repeated-state loops (same hash appearing
repeatedly means the Agent isn't making progress).
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

# ---------------------------------------------------------------------------
# Fields explicitly excluded (change every iteration, not meaningful)
# ---------------------------------------------------------------------------
EXCLUDED_FIELDS = {
    "timestamp",
    "trace_id",
    "iteration_count",
}


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
