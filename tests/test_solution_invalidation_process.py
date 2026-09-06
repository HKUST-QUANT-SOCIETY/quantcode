"""P-10 Solution decision-lock recovery tests across a real process death."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from runner.solution_workflow import PHASE_DENY_MESSAGE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPRO_SCRIPT = PROJECT_ROOT / "scripts" / "repro_solution_invalidation.py"


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="requires SIGKILL")
def test_recovered_checkpoint_rejects_same_id_frozen_solution_replacement(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPRO_SCRIPT), "--workdir", str(tmp_path / "p10-recovery")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    observation = json.loads(result.stdout)
    assert observation["crash_returncode"] == -signal.SIGKILL
    assert observation["original_doc_hash"] != observation["replacement_doc_hash"]
    assert observation["resumed"]["solution_phase"] == "invalid"
    assert PHASE_DENY_MESSAGE in observation["resumed"]["tool_result"]
    assert observation["resumed"]["side_effects"] == []
