"""Process-level failure tests for durable external tool receipts."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPRO_SCRIPT = PROJECT_ROOT / "scripts" / "repro_tool_receipt_crash.py"


def run_scenario(tmp_path: Path, scenario: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(REPRO_SCRIPT),
            "--scenario",
            scenario,
            "--workdir",
            str(tmp_path / scenario),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="requires SIGKILL")
def test_sigkill_before_external_write_safely_retries_once(tmp_path):
    observation = run_scenario(tmp_path, "before-side-effect")

    assert observation["crash_returncode"] == -signal.SIGKILL
    assert observation["after_restart"] == {
        "executed": True,
        "result": {"external_id": "report-1"},
        "status": "executed",
    }
    assert observation["external_write_count"] == 1
    assert observation["unresolved_receipts"] == []


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="requires SIGKILL")
def test_sigkill_after_external_write_blocks_automatic_retry(tmp_path):
    observation = run_scenario(tmp_path, "after-side-effect")

    assert observation["crash_returncode"] == -signal.SIGKILL
    assert observation["after_restart"]["status"] == "blocked_unknown"
    assert observation["after_restart"]["executed"] is False
    assert observation["external_write_count"] == 1
    assert observation["unresolved_receipts"][0]["receipt_status"] == "STARTED"


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="requires SIGKILL")
def test_sigkill_after_completed_receipt_replays_without_external_write(tmp_path):
    observation = run_scenario(tmp_path, "after-completion")

    assert observation["crash_returncode"] == -signal.SIGKILL
    assert observation["after_restart"] == {
        "executed": False,
        "result": {"external_id": "report-1"},
        "status": "replayed",
    }
    assert observation["external_write_count"] == 1
    assert observation["unresolved_receipts"] == []


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="requires SIGKILL")
def test_concurrent_resume_is_busy_then_unknown_after_holder_is_killed(tmp_path):
    observation = run_scenario(tmp_path, "concurrent-resume")

    assert observation["while_locked"]["status"] == "busy"
    assert observation["while_locked"]["executed"] is False
    assert observation["crash_returncode"] == -signal.SIGKILL
    assert observation["after_restart"]["status"] == "blocked_unknown"
    assert observation["after_restart"]["executed"] is False
    assert observation["external_write_count"] == 1
    assert observation["unresolved_receipts"][0]["receipt_status"] == "STARTED"
