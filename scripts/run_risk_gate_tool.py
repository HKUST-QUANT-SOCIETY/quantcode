"""CLI bridge for OpenCode to run QuantCode risk:gate.

This script is intentionally small and deterministic: it runs the local
risk:gate LangGraph flow with the Day 3 stub data and prints one JSON object to
stdout. OpenCode custom tools call this script from TypeScript.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flows.risk_gate import build_workflow, resume_risk_gate  # noqa: E402
from runner.compose_executor import execute_compose_flow, register_flow, unregister_flow  # noqa: E402
from runner.langgraph_base import clear_checkpointer_cache, make_thread_id  # noqa: E402
from tools.risk.risk_tools import clear_write_pr_comment_dedupe_cache  # noqa: E402


def _fixture_model_spec() -> dict[str, Any]:
    path = PROJECT_ROOT / "tests/fixtures/sample_model/model_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _flow_input(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "scenario": args.scenario,
        "model_spec": _fixture_model_spec(),
        "pr_number": args.pr_number,
        "head_sha": args.head_sha,
        "pr_url": args.pr_url
        or f"https://github.com/hkust-quant-society/quantcode/pull/{args.pr_number}",
        "artifacts_root": str(PROJECT_ROOT / "artifacts" / "risk" / "opencode" / args.scenario),
        "dedupe_db_path": str(PROJECT_ROOT / ".quantcode" / "opencode-dedupe.sqlite"),
    }


def _normal(args: argparse.Namespace) -> dict[str, Any]:
    thread_id = args.thread_id or make_thread_id("risk", "risk:gate", suffix="opencode-normal")
    app = build_workflow(checkpoint_db=PROJECT_ROOT / ".quantcode" / "opencode-checkpoints.db")
    register_flow("risk", "risk:gate", app, overwrite=True)
    try:
        result = execute_compose_flow(
            group="risk",
            flow_name="risk:gate",
            input_data=_flow_input(args),
            thread_id=thread_id,
        )
    finally:
        unregister_flow("risk", "risk:gate")
    return {
        "thread_id": result["thread_id"],
        "status": result["output_data"]["status"],
        "output_data": result["output_data"],
        "artifacts": result["artifacts"],
        "interrupted": False,
    }


def _high_risk(args: argparse.Namespace) -> dict[str, Any]:
    thread_id = args.thread_id or make_thread_id("risk", "risk:gate", suffix="opencode-high-risk")
    app = build_workflow(checkpoint_db=PROJECT_ROOT / ".quantcode" / "opencode-checkpoints.db")
    config = {"configurable": {"thread_id": thread_id}}
    init_state = {
        "group": "risk",
        "flow_name": "risk:gate",
        "thread_id": thread_id,
        "input_data": _flow_input(args),
        "output_data": None,
        "artifacts": [],
        "errors": [],
    }

    paused = app.invoke(init_state, config=config)
    interrupt_payload = paused["__interrupt__"][0].value

    if args.decision == "pending":
        return {
            "thread_id": thread_id,
            "status": "waiting_for_human",
            "interrupted": True,
            "interrupt": interrupt_payload,
            "artifacts": paused.get("artifacts", []),
        }

    result = resume_risk_gate(app, thread_id, args.decision)
    return {
        "thread_id": thread_id,
        "status": result["output_data"]["status"],
        "interrupted": True,
        "interrupt": interrupt_payload,
        "decision": args.decision,
        "output_data": result["output_data"],
        "artifacts": result["artifacts"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run QuantCode risk:gate for OpenCode.")
    parser.add_argument("--scenario", choices=["normal", "high_risk"], default="normal")
    parser.add_argument("--decision", choices=["approve", "reject", "pending"], default="approve")
    parser.add_argument("--pr-number", default="303")
    parser.add_argument("--head-sha", default="opencode1234567890abcdef")
    parser.add_argument("--pr-url", default=None)
    parser.add_argument("--thread-id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = _high_risk(args) if args.scenario == "high_risk" else _normal(args)
    finally:
        clear_checkpointer_cache()
        clear_write_pr_comment_dedupe_cache()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
