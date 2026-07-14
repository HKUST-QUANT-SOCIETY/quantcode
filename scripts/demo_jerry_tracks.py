#!/usr/bin/env python3
"""Day 5 demo CLI — strategy / fundamental / options 三组收口（刘炽）。

用法::

    python scripts/demo_jerry_tracks.py --track all
    python scripts/demo_jerry_tracks.py --track fundamental
    python scripts/demo_jerry_tracks.py --track options --json

也可经 demo_bridge 同一链路（需 LLM）::

    python -m runner.demo_bridge --group strategy --task "组合 PB-ROE + 动量信号"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# repo root on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runner.jerry_demos import (  # noqa: E402
    run_all_demos,
    run_fundamental_demo,
    run_options_demo,
    run_strategy_demo,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantCode Day5 Jerry track demos")
    parser.add_argument(
        "--track",
        choices=["strategy", "fundamental", "options", "all"],
        default="all",
    )
    parser.add_argument("--json", action="store_true", help="只输出 JSON 结果")
    args = parser.parse_args(argv)

    runners = {
        "strategy": run_strategy_demo,
        "fundamental": run_fundamental_demo,
        "options": run_options_demo,
        "all": run_all_demos,
    }
    result = runners[args.track]()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        items = result.items() if args.track == "all" else [(args.track, result)]
        for name, data in items:
            print(f"\n=== {name} ===")
            print(f"  schema   : {data.get('schema')}")
            print(f"  artifact : {data.get('artifact_path')}")
            if name == "fundamental":
                print(
                    f"  PIT      : filtered={data.get('pit_filtered_count')} "
                    f"docs={data.get('pit_doc_count')} backend={data.get('pit_backend')}"
                )
                print(f"  human    : {data.get('human_gate')}")
                print(
                    f"  report   : md_filled={data.get('markdown_filled')} "
                    f"pdf_filled={data.get('pdf_filled')} typst={data.get('typst_used')}"
                )
                print(f"  markdown : {data.get('markdown_path')}")
                print(f"  pdf      : {data.get('pdf_path')}")
            if name == "options":
                print(f"  delta    : {data.get('portfolio_delta')}")
                print(f"  sharpe   : {data.get('backtest_sharpe')}")
            if name == "strategy":
                print(f"  verdict  : {data.get('verdict')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
