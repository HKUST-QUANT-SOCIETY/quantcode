#!/usr/bin/env python3
"""Reproduce LangGraph checkpoint recovery across a real SIGKILL restart."""
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

from runner.compose_executor import execute_compose_flow, register_flow  # noqa: E402
from runner.langgraph_base import (  # noqa: E402
    create_workflow,
    default_compose_edges,
    get_checkpointer,
)


GROUP = "factor"
FLOW_NAME = "fault:checkpoint-recovery"
THREAD_ID = "factor-fault-checkpoint-recovery-1"


def _durable_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _mark(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _run_worker(workdir: Path, *, resume: bool) -> dict[str, Any]:
    events = workdir / "node-events.log"
    crash_marker = workdir / "crash-marker"
    allow_completion = workdir / "allow-completion"

    def step_a(state: dict[str, Any]) -> dict[str, Any]:
        _durable_write(events, "step_a")
        return {"artifacts": ["step_a.txt"]}

    def step_b(state: dict[str, Any]) -> dict[str, Any]:
        if not allow_completion.exists():
            _durable_write(events, "step_b_started")
            _mark(crash_marker, "step-b-entered")
            os.kill(os.getpid(), signal.SIGKILL)
            raise AssertionError("SIGKILL returned unexpectedly")  # pragma: no cover
        _durable_write(events, "step_b_resumed")
        return {"artifacts": ["step_b.txt"]}

    def step_c(state: dict[str, Any]) -> dict[str, Any]:
        _durable_write(events, "step_c")
        return {"artifacts": ["step_c.txt"], "output_data": {"status": "success"}}

    workflow = create_workflow(
        nodes={"step_a": step_a, "step_b": step_b, "step_c": step_c},
        edges=default_compose_edges(["step_a", "step_b", "step_c"]),
    )
    app = workflow.compile(checkpointer=get_checkpointer(workdir / "checkpoints.db"))
    register_flow(GROUP, FLOW_NAME, app, overwrite=True)
    return execute_compose_flow(
        GROUP,
        FLOW_NAME,
        {} if resume else {"request": "reproduce-process-kill"},
        thread_id=THREAD_ID,
        resume=resume,
    )


def _wait_for_marker(process: subprocess.Popen[str], marker: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return
        returncode = process.poll()
        if returncode is not None:
            stderr = process.stderr.read().strip() if process.stderr else ""
            raise RuntimeError(f"worker exited with {returncode} before checkpoint crash: {stderr}")
        time.sleep(0.01)
    process.kill()
    process.wait(timeout=5)
    raise TimeoutError("worker did not reach the checkpoint crash boundary")


def run_scenario(workdir: Path) -> dict[str, Any]:
    if not hasattr(signal, "SIGKILL"):
        raise RuntimeError("this recovery scenario requires SIGKILL")
    workdir.mkdir(parents=True, exist_ok=True)
    script = str(Path(__file__).resolve())
    worker = subprocess.Popen(
        [sys.executable, script, "--worker", "start", "--workdir", str(workdir)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for_marker(worker, workdir / "crash-marker")
    crash_returncode = worker.wait(timeout=10)
    if worker.stdout:
        worker.stdout.close()
    if worker.stderr:
        worker.stderr.close()

    _mark(workdir / "allow-completion", "resume-can-complete")
    resumed = subprocess.run(
        [sys.executable, script, "--worker", "resume", "--workdir", str(workdir)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if resumed.returncode != 0:
        raise RuntimeError(
            f"resume worker exited with {resumed.returncode}: {resumed.stderr.strip()}"
        )
    events = (workdir / "node-events.log").read_text(encoding="utf-8").splitlines()
    return {
        "crash_returncode": crash_returncode,
        "events": events,
        "resumed": json.loads(resumed.stdout),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("start", "resume"))
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    workdir = args.workdir.resolve()
    if args.worker:
        result = _run_worker(workdir, resume=args.worker == "resume")
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    print(json.dumps(run_scenario(workdir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
