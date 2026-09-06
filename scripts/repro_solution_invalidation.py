#!/usr/bin/env python3
"""Reproduce P-10 frozen-Solution replacement across checkpoint recovery."""
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

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langgraph.graph import END, START  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from runner.agent_nodes import AgentState, make_tool_node  # noqa: E402
from runner.langgraph_base import create_workflow, get_checkpointer  # noqa: E402
from runner.solution_workflow import (  # noqa: E402
    SolutionStore,
    add_round,
    compute_doc_hash,
    freeze_solution,
    start_solution,
)
from tools.registry import ToolDef, ToolRegistry  # noqa: E402

THREAD_ID = "factor-p10-invalidated-solution-1"


class _WriteArgs(BaseModel):
    path: str


def _mark(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _worker(workdir: Path, *, resume: bool) -> dict[str, Any]:
    side_effects = workdir / "side-effects.log"
    crash_marker = workdir / "crash-marker"
    allow_resume = workdir / "allow-resume"

    def write(args: _WriteArgs, _ctx: dict[str, Any]) -> str:
        with side_effects.open("a", encoding="utf-8") as handle:
            handle.write(args.path + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return f"wrote {args.path}"

    registry = ToolRegistry()
    registry.register(ToolDef(
        id="write_blackboard",
        description="P-10 recovery side-effect probe",
        schema=_WriteArgs,
        execute=write,
    ))
    tool_node = make_tool_node(registry)

    def crash_boundary(_state: AgentState) -> dict[str, Any]:
        if not allow_resume.exists():
            _mark(crash_marker, "checkpoint-created")
            os.kill(os.getpid(), signal.SIGKILL)
            raise AssertionError("SIGKILL returned unexpectedly")  # pragma: no cover
        return {}

    workflow = create_workflow(
        nodes={"crash_boundary": crash_boundary, "tool": tool_node},
        edges=[(START, "crash_boundary"), ("crash_boundary", "tool"), ("tool", END)],
        state_schema=AgentState,
    )
    app = workflow.compile(checkpointer=get_checkpointer(workdir / "checkpoints.db"))
    config = {"configurable": {"thread_id": THREAD_ID}}

    if resume:
        result = app.invoke(None, config=config)
    else:
        store = SolutionStore(
            blackboard_db_path=workdir / "blackboard.db",
            artifacts_dir=workdir / "solutions",
        )
        original = store.get("sol-p10-recovery")
        if original is None:
            raise RuntimeError("original frozen SolutionDoc is missing")
        initial: AgentState = {
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "write_blackboard",
                "args": {"path": "original.py"},
                "id": "write-original",
            }])],
            "group": "factor",
            "thread_id": THREAD_ID,
            "solution_phase": "frozen",
            "solution_id": original.id,
            "solution_doc_hash": original.doc_hash,
            "solution_required": True,
            "capability_catalog_checked": True,
            "_blackboard_db_path": str(workdir / "blackboard.db"),
            "artifacts": [],
            "errors": [],
        }
        result = app.invoke(initial, config=config)

    tool_messages = [
        message for message in (result.get("messages") or [])
        if isinstance(message, ToolMessage)
    ]
    return {
        "solution_phase": result.get("solution_phase"),
        "solution_doc_hash": result.get("solution_doc_hash"),
        "tool_result": tool_messages[-1].content if tool_messages else None,
        "side_effects": (
            side_effects.read_text(encoding="utf-8").splitlines()
            if side_effects.exists() else []
        ),
    }


def _wait_for_marker(process: subprocess.Popen[str], marker: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return
        returncode = process.poll()
        if returncode is not None:
            stderr = process.stderr.read().strip() if process.stderr else ""
            raise RuntimeError(f"worker exited with {returncode} before SIGKILL: {stderr}")
        time.sleep(0.01)
    process.kill()
    process.wait(timeout=5)
    raise TimeoutError("worker did not reach the checkpoint boundary")


def run_scenario(workdir: Path) -> dict[str, Any]:
    if not hasattr(signal, "SIGKILL"):
        raise RuntimeError("this recovery scenario requires SIGKILL")
    workdir.mkdir(parents=True, exist_ok=True)
    store = SolutionStore(
        blackboard_db_path=workdir / "blackboard.db",
        artifacts_dir=workdir / "solutions",
    )
    original = start_solution(
        "原冻结方案",
        doc_id="sol-p10-recovery",
        file_impact=["original.py"],
        store=store,
    )
    add_round(original.id, "第一轮确认", store=store)
    add_round(original.id, "第二轮确认", store=store)
    original = freeze_solution(original.id, confirm=True, store=store)

    script = str(Path(__file__).resolve())
    first = subprocess.Popen(
        [sys.executable, script, "--worker", "start", "--workdir", str(workdir)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for_marker(first, workdir / "crash-marker")
    crash_returncode = first.wait(timeout=10)

    replacement = original.model_copy(update={
        "goal": "同 id 的替换方案",
        "file_impact": ["replacement.py"],
        "version": original.version + 1,
    })
    replacement = replacement.model_copy(
        update={"doc_hash": compute_doc_hash(replacement)}
    )
    store.save(replacement)
    _mark(workdir / "allow-resume", "resume")

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
    return {
        "crash_returncode": crash_returncode,
        "original_doc_hash": original.doc_hash,
        "replacement_doc_hash": replacement.doc_hash,
        "resumed": json.loads(resumed.stdout),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("start", "resume"))
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    workdir = args.workdir.resolve()
    if args.worker:
        print(json.dumps(_worker(workdir, resume=args.worker == "resume"), sort_keys=True))
    else:
        print(json.dumps(run_scenario(workdir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
