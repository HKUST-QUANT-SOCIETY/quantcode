"""Checkpoint recovery tests that cross a real process death boundary."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPRO_SCRIPT = PROJECT_ROOT / "scripts" / "repro_checkpoint_sigkill.py"


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="requires SIGKILL")
def test_checkpoint_resume_after_sigkill_does_not_repeat_completed_node(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPRO_SCRIPT), "--workdir", str(tmp_path / "checkpoint-kill")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    observation = json.loads(result.stdout)
    assert observation["crash_returncode"] == -signal.SIGKILL
    assert observation["events"] == [
        "step_a",
        "step_b_started",
        "step_b_resumed",
        "step_c",
    ]
    assert observation["resumed"]["artifacts"] == [
        "step_a.txt",
        "step_b.txt",
        "step_c.txt",
    ]
    assert observation["resumed"]["output_data"] == {"status": "success"}
