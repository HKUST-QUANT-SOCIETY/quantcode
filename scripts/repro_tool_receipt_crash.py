#!/usr/bin/env python3
"""Reproduce durable tool-receipt failures with real OS processes.

The controller starts this file again in worker mode so the receipt store and
the simulated external system are separated from the observing process.  The
worker is terminated with SIGKILL at deterministic markers; no graceful Python
cleanup runs at the crash boundary.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runner.tool_receipts import (  # noqa: E402
    ToolOutcomeUnknown,
    execute_once,
    unresolved_receipts,
)


CALL = {"id": "call-1", "name": "write_report", "args": {"report": "report-1"}}
CONTEXT = {
    "thread_id": "task-1",
    "actor_id": "writer",
    "role": "analyst",
    "group": "factor",
    "workspace_id": "workspace-1",
    "workspace_path": "/workspaces/factor",
    "github_subject": "writer-gh",
    "resource_scopes": ["reports:write"],
}


def _durable_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _mark(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _external_write(workdir: Path) -> dict[str, str]:
    _durable_write(
        workdir / "external-writes.jsonl",
        json.dumps({"event": "write_report", "pid": os.getpid()}, sort_keys=True) + "\n",
    )
    return {"external_id": "report-1"}


def _worker(workdir: Path, mode: str) -> int:
    database = workdir / "tool-receipts.db"
    marker = workdir / "crash-marker"

    if mode == "crash-before-side-effect":
        # This marker is deliberately before execute_once reserves a receipt or
        # calls the external system. A new process can therefore retry safely.
        _mark(marker, "before-protected-tool-invocation")
        os.kill(os.getpid(), signal.SIGKILL)
        return 70  # pragma: no cover - SIGKILL cannot return

    if mode == "crash-after-side-effect":

        def crash_after_side_effect() -> dict[str, str]:
            result = _external_write(workdir)
            _mark(marker, "side-effect-durable")
            os.kill(os.getpid(), signal.SIGKILL)
            return result  # pragma: no cover - SIGKILL cannot return

        execute_once(database, CALL, CONTEXT, crash_after_side_effect)
        return 70  # pragma: no cover - SIGKILL cannot return

    if mode == "crash-after-completion":
        execute_once(database, CALL, CONTEXT, lambda: _external_write(workdir))
        _mark(marker, "receipt-completed")
        os.kill(os.getpid(), signal.SIGKILL)
        return 70  # pragma: no cover - SIGKILL cannot return

    if mode == "hold-after-side-effect":

        def hold_after_side_effect() -> dict[str, str]:
            result = _external_write(workdir)
            _mark(marker, "lock-held")
            while True:
                signal.pause()
            return result  # pragma: no cover - parent sends SIGKILL

        execute_once(database, CALL, CONTEXT, hold_after_side_effect)
        return 70  # pragma: no cover - parent sends SIGKILL

    if mode == "attempt-resume":
        executed = False

        def retry_write() -> dict[str, str]:
            nonlocal executed
            executed = True
            return _external_write(workdir)

        try:
            result = execute_once(database, CALL, CONTEXT, retry_write)
        except ToolOutcomeUnknown as exc:
            observation: dict[str, Any] = {
                "status": "blocked_unknown",
                "error": str(exc),
                "executed": executed,
            }
        except RuntimeError as exc:
            if "RUN_BUSY" not in str(exc):
                raise
            observation = {"status": "busy", "error": str(exc), "executed": executed}
        else:
            observation = {
                "status": "executed" if executed else "replayed",
                "result": result,
                "executed": executed,
            }
        print(json.dumps(observation, sort_keys=True), flush=True)
        return 0

    raise ValueError(f"unsupported worker mode: {mode}")


def _wait_for_marker(process: subprocess.Popen[str], marker: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(f"worker exited with {returncode} before creating {marker.name}")
        time.sleep(0.01)
    process.kill()
    process.wait(timeout=5)
    raise TimeoutError(f"worker did not create {marker.name} within {timeout:.1f}s")


def _start_worker(workdir: Path, mode: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            mode,
            "--workdir",
            str(workdir),
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _attempt_resume(workdir: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "attempt-resume",
            "--workdir",
            str(workdir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"resume worker exited with {result.returncode}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def _external_write_count(workdir: Path) -> int:
    path = workdir / "external-writes.jsonl"
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def run_scenario(workdir: Path, scenario: str) -> dict[str, Any]:
    if not hasattr(signal, "SIGKILL"):
        raise RuntimeError("these recovery scenarios require SIGKILL")
    workdir.mkdir(parents=True, exist_ok=True)
    marker = workdir / "crash-marker"

    mode = {
        "before-side-effect": "crash-before-side-effect",
        "after-side-effect": "crash-after-side-effect",
        "after-completion": "crash-after-completion",
        "concurrent-resume": "hold-after-side-effect",
    }[scenario]
    process = _start_worker(workdir, mode)
    _wait_for_marker(process, marker)

    if scenario == "concurrent-resume":
        while_locked = _attempt_resume(workdir)
        process.kill()
    else:
        while_locked = None

    crash_returncode = process.wait(timeout=10)
    if process.stdout:
        process.stdout.close()
    if process.stderr:
        process.stderr.close()
    after_restart = _attempt_resume(workdir)
    unresolved = unresolved_receipts(workdir / "tool-receipts.db", CONTEXT["thread_id"])

    return {
        "scenario": scenario,
        "crash_returncode": crash_returncode,
        "while_locked": while_locked,
        "after_restart": after_restart,
        "external_write_count": _external_write_count(workdir),
        "unresolved_receipts": unresolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "before-side-effect",
            "after-side-effect",
            "after-completion",
            "concurrent-resume",
        ),
    )
    parser.add_argument(
        "--worker",
        choices=(
            "crash-before-side-effect",
            "crash-after-side-effect",
            "crash-after-completion",
            "hold-after-side-effect",
            "attempt-resume",
        ),
    )
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.scenario) == bool(args.worker):
        parser.error("provide exactly one of --scenario or --worker")
    if args.worker:
        return _worker(args.workdir.resolve(), args.worker)
    print(json.dumps(run_scenario(args.workdir.resolve(), args.scenario), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
