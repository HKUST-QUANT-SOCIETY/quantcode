"""Tests for runner.routing.rlhf_logger — RLHF jsonl append logging (Day 5 format)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from runner.routing.rlhf_logger import (
    RLHF_PATH,
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
            iteration=3,
            system_decision="continue",
            human_decision="",
            risk_features={"tail_risk_var_99": 0.03},
            checkpoint_id="ck-001",
        )
        assert entry["thread_id"] == "risk-demo-001"
        assert entry["group"] == "risk"
        assert entry["state_fingerprint"] == "abc123"
        assert entry["action"]["tool_name"] == "calc_risk_stub"
        assert entry["observation"]["success"] is True
        assert entry["system_decision"] == "continue"
        assert entry["human_decision"] == ""
        assert entry["gate_purpose"] == "normal"    # continue → normal
        assert entry["label"] is None               # no human_decision, no label
        assert entry["risk_score"] is not None
        assert entry["risk_features"] == {"tail_risk_var_99": 0.03}
        assert entry["checkpoint_id"] == "ck-001"
        assert entry["metadata"]["iteration"] == 3
        # Day 5: reward_key and reward fields are removed
        assert "reward" not in entry

    def test_gate_correct_label_1(self):
        """human_gate + abort → label=1 (system correctly blocked)."""
        entry = make_rlhf_entry(
            system_decision="human_gate",
            human_decision="abort",
            risk_features={"tail_risk_var_99": 0.06},
        )
        assert entry["gate_purpose"] == "risk"
        assert entry["label"] == 1

    def test_gate_false_positive_label_0(self):
        """human_gate + proceed → label=0 (false positive)."""
        entry = make_rlhf_entry(
            system_decision="human_gate",
            human_decision="proceed",
            risk_features={"tail_risk_var_99": 0.06},
        )
        assert entry["gate_purpose"] == "risk"
        assert entry["label"] == 0

    def test_abort_loop_gate_purpose(self):
        """abort_loop → gate_purpose='loop', no label (not risk)."""
        entry = make_rlhf_entry(
            system_decision="abort_loop",
            human_decision="proceed",
        )
        assert entry["gate_purpose"] == "loop"
        assert entry["label"] is None

    def test_unknown_system_decision_returns_empty_gate_purpose(self):
        entry = make_rlhf_entry(system_decision="unknown_xyz")
        assert entry["gate_purpose"] == ""

    def test_risk_score_zero_for_normal_metrics(self):
        entry = make_rlhf_entry(
            risk_features={"tail_risk_var_99": 0.001, "max_drawdown": 0.01}
        )
        # max(0.001/0.05=0.02, 0.01/0.15=0.0667, 0, 0) = 0.0667
        assert entry["risk_score"] == 0.0667
        assert entry["risk_score"] is not None

    def test_risk_score_none_when_no_features(self):
        entry = make_rlhf_entry()
        assert entry["risk_score"] is None

    def test_empty_risk_features_returns_none_score(self):
        entry = make_rlhf_entry(risk_features={})
        assert entry["risk_score"] is None

    def test_metadata_no_route_field(self):
        """Day 5: metadata no longer has 'route' key."""
        entry = make_rlhf_entry()
        assert "route" not in entry["metadata"]


class TestLogRlhfEntry:
    def test_writes_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonl"
            entry = make_rlhf_entry(tool_name="test")
            log_rlhf_entry(entry, path=path)
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 1

    def test_appends_not_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.jsonl"
            e1 = make_rlhf_entry(tool_name="a", iteration=1)
            e2 = make_rlhf_entry(tool_name="b", iteration=2)
            log_rlhf_entry(e1, path=path)
            log_rlhf_entry(e2, path=path)
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
            e = make_rlhf_entry()
            log_rlhf_entry(e, path=path)
            assert path.exists()
