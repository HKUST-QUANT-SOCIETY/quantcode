"""Run the deterministic Model→Risk CI compatibility flow."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from runner.compose_executor import execute_compose_flow, register_flow, unregister_flow  # noqa: E402
from runner.langgraph_base import clear_checkpointer_cache, make_thread_id  # noqa: E402
from runner.risk_ci import build_risk_ci_flow  # noqa: E402
from tools.risk.risk_tools import clear_write_pr_comment_dedupe_cache  # noqa: E402


def _fixture_model_spec() -> dict[str, Any]:
    return json.loads(
        (PROJECT_ROOT / "tests/fixtures/sample_model/model_spec.json").read_text(
            encoding="utf-8"
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run QuantCode risk CI evaluation.")
    parser.add_argument("--scenario", choices=["normal", "high_risk"], default="normal")
    parser.add_argument("--pr-number", default="303")
    parser.add_argument("--head-sha", default="ci1234567890abcdef")
    parser.add_argument("--pr-url", default=None)
    parser.add_argument("--thread-id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # This entry point is intentionally a deterministic fixture-backed CI
    # compatibility run. Mark that boundary explicitly so the risk adapter's
    # production fail-closed rule cannot be bypassed by ordinary callers.
    os.environ.setdefault("QUANTCODE_ENV", "test")
    thread_id = args.thread_id or make_thread_id("risk", "risk:ci")
    app = build_risk_ci_flow(PROJECT_ROOT / ".quantcode" / "ci-checkpoints.db")
    register_flow("risk", "risk:ci", app, overwrite=True)
    try:
        result = execute_compose_flow(
            group="risk",
            flow_name="risk:ci",
            input_data={
                "scenario": args.scenario,
                "model_spec": _fixture_model_spec(),
                "pr_number": args.pr_number,
                "head_sha": args.head_sha,
                "pr_url": args.pr_url
                or f"https://github.com/hkust-quant-society/quantcode/pull/{args.pr_number}",
                "artifacts_root": str(PROJECT_ROOT / "artifacts" / "risk" / "ci"),
                "dedupe_db_path": str(PROJECT_ROOT / ".quantcode" / "ci-dedupe.sqlite"),
            },
            thread_id=thread_id,
        )
    finally:
        unregister_flow("risk", "risk:ci")
        clear_checkpointer_cache()
        clear_write_pr_comment_dedupe_cache()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
