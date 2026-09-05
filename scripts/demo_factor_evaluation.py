"""Minimal standup demo for factor:evaluation."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flows.factor_evaluation_adapter import build_workflow
from runner.compose_executor import execute_compose_flow, register_flow, unregister_flow
from runner.langgraph_base import clear_checkpointer_cache, make_thread_id


def main() -> None:
    thread_id = make_thread_id("factor", "factor:evaluation", suffix="standup")
    app = build_workflow()
    input_data = {
        "name": "pb_roe_combo",
        "campaign_id": "campaign_2026q2",
        "formula": "tests.fixtures.sample_factor:pb_roe_combo",
        "domain": "equity",
        "frequency": "daily",
        "universe": "CSI1000",
        "operators": ["roe_ttm", "pb", "divide"],
        "estimated_runtime_seconds": 30,
        "date_range": {"start": "2023-01-01", "end": "2025-12-31"},
        "benchmark": "HS300",
        "forward_return_horizon": 5,
    }

    register_flow("factor", "factor:evaluation", app, overwrite=True)
    try:
        result = execute_compose_flow(
            group="factor",
            flow_name="factor:evaluation",
            input_data=input_data,
            thread_id=thread_id,
        )
    finally:
        unregister_flow("factor", "factor:evaluation")
        clear_checkpointer_cache()

    print("thread_id:", result["thread_id"])
    print("component:", result["output_data"]["component_id"])
    print("status:", result["output_data"]["result_status"])
    print("errors:", result["errors"])


if __name__ == "__main__":
    main()
