"""Tests for runner.routing.fingerprint — state fingerprinting."""
from __future__ import annotations

import pytest

from runner.routing.fingerprint import compute_state_fingerprint


def _state(**overrides):
    """Minimal builder so tests stay readable."""
    base = {
        "current_step": "execute_tool",
        "last_tool": "fetch_data",
        "tool_args": {"symbol": "000001.SZ"},
        "output_data": {"price": 12.34},
        "errors": None,
        "timestamp": "2026-07-05T10:00:00Z",
        "trace_id": "abc-123",
        "iteration_count": 7,
    }
    base.update(overrides)
    return base


class TestSameStateSameFingerprint:
    """Identical business state → identical hash."""

    def test_same_state_same_hash(self):
        a = _state()
        b = _state()
        assert compute_state_fingerprint(a) == compute_state_fingerprint(b)

    def test_volatile_fields_ignored(self):
        """timestamp / trace_id / iteration_count changes must NOT affect hash."""
        a = _state()
        b = _state(
            timestamp="2026-07-05T11:00:00Z",
            trace_id="xyz-999",
            iteration_count=99,
        )
        assert compute_state_fingerprint(a) == compute_state_fingerprint(b)


class TestBusinessFieldChangeChangesFingerprint:
    """When a business-significant field changes, the hash MUST change."""

    def test_current_step_change(self):
        a = _state(current_step="execute_tool")
        b = _state(current_step="human_gate")
        assert compute_state_fingerprint(a) != compute_state_fingerprint(b)

    def test_last_tool_change(self):
        a = _state(last_tool="fetch_data")
        b = _state(last_tool="calc_risk")
        assert compute_state_fingerprint(a) != compute_state_fingerprint(b)

    def test_tool_args_change(self):
        a = _state(tool_args={"symbol": "000001.SZ"})
        b = _state(tool_args={"symbol": "600519.SH"})
        assert compute_state_fingerprint(a) != compute_state_fingerprint(b)

    def test_output_data_change(self):
        a = _state(output_data={"price": 12.34})
        b = _state(output_data={"price": 99.99})
        assert compute_state_fingerprint(a) != compute_state_fingerprint(b)

    def test_errors_change(self):
        a = _state(errors=None)
        b = _state(errors="connection timeout")
        assert compute_state_fingerprint(a) != compute_state_fingerprint(b)


class TestEdgeCases:
    def test_empty_state_gives_deterministic_hash(self):
        h1 = compute_state_fingerprint({})
        h2 = compute_state_fingerprint({})
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_hash_is_hex_string(self):
        h = compute_state_fingerprint(_state())
        assert isinstance(h, str)
        assert all(c in "0123456789abcdef" for c in h)
