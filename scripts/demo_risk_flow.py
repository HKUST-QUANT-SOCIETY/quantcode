"""Day 3 standup demo — thin wrapper around scripts/run_risk_ci_tool.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLI = PROJECT_ROOT / "scripts" / "run_risk_ci_tool.py"


def _run(args: list[str]) -> None:
    cmd = [sys.executable, str(CLI), *args]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    print("QuantCode Day 3 — risk:ci Demo (via run_risk_ci_tool.py)")
    _run(["--scenario", "normal", "--pr-number", "101", "--head-sha", "demo1234567890abcdef"])
    _run([
        "--scenario", "high_risk",
        "--pr-number", "202",
        "--head-sha", "demo1234567890abcdef",
    ])
    print("\nDemo 完成 — 详见 artifacts/risk/ci/")


if __name__ == "__main__":
    main()
