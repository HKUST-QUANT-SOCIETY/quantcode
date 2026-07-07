"""Tests for runner.routing.rlhf_logger — RLHF jsonl append logging."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

# import pytest

from runner.routing.rlhf_logger import (
    REWARD,
    log_rlhf_entry,
    make_rlhf_entry,
)


class TestMakeRlhfEntry:
    def test_all_fields_present(self):
        entry = make_rlhf_entry(
            thread_id="risk-demo-001",
            group="risk",
            state_fingerprint="abc123",
            tool_name="calc_risk_stub",
            tool_args={"scenario": "normal"},
            success=True,
            summary="risk metrics generated",
            reward_key="tool_success",
            iteration=3,
            route="continue",
        )
        assert entry["thread_id"] == "risk-demo-001"
        assert entry["group"] == "risk"
        assert entry["state_fingerprint"] == "abc123"
        assert entry["action"]["tool_name"] == "calc_risk_stub"
        assert entry["observation"]["success"] is True
        assert entry["reward"] == REWARD["tool_success"]
        assert entry["metadata"]["iteration"] == 3
        assert entry["metadata"]["route"] == "continue"

    def test_unknown_reward_key_returns_zero(self):
        entry = make_rlhf_entry(reward_key="nonexistent")
        assert entry["reward"] == 0

    def test_tool_failure_reward(self):
        entry = make_rlhf_entry(success=False, reward_key="tool_failure")
        assert entry["reward"] == REWARD["tool_failure"]


class TestLogRlhfEntry:
    def test_writes_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonl"
            log_rlhf_entry({"action": {"tool_name": "test"}, "reward": 1}, path=path)
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 1

    def test_appends_not_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonl"
            log_rlhf_entry({"n": 1}, path=path)
            log_rlhf_entry({"n": 2}, path=path)
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2

    def test_json_is_parseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonl"
            entry = make_rlhf_entry(
                thread_id="demo",
                group="risk",
                tool_name="stub",
            )
            log_rlhf_entry(entry, path=path)
            parsed = json.loads(path.read_text().strip())
            assert parsed["action"]["tool_name"] == "stub"

    def test_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "nested" / "rlhf.jsonl"
            log_rlhf_entry({"x": 1}, path=path)
            assert path.exists()
