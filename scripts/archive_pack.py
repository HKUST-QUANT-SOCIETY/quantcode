#!/usr/bin/env python3
"""Pack Jerry demo artifacts into ``archives/`` for handoff / 汇报.

Usage::

    # Re-run demos and archive (default)
    python3 scripts/archive_pack.py --track all

    # Archive whatever is already in the latest demo result paths
    # (re-runs demos under the hood so paths exist)
    python3 scripts/archive_pack.py --track fundamental

    # List existing packs
    python3 scripts/archive_pack.py --list
    python3 scripts/archive_pack.py --list --group options
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from runner.archive_pack import list_archives, pack_jerry_demo_results  # noqa: E402
from runner.jerry_demos import (  # noqa: E402
    run_all_demos,
    run_fundamental_demo,
    run_options_demo,
    run_strategy_demo,
)
from schemas.archive import ArchiveSource  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantCode demo archive packer")
    parser.add_argument(
        "--track",
        choices=["strategy", "fundamental", "options", "all"],
        default="all",
    )
    parser.add_argument("--list", action="store_true", help="List existing archives")
    parser.add_argument("--group", default=None, help="Filter --list by group")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--source",
        choices=[s.value for s in ArchiveSource],
        default=ArchiveSource.MANUAL.value,
        help="manifest.source tag (default: manual when using this CLI)",
    )
    args = parser.parse_args(argv)

    if args.list:
        rows = list_archives(group=args.group)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            if not rows:
                print("(no archives)")
            for r in rows:
                print(
                    f"{r['archive_id']}  group={r['group']}  "
                    f"files={r['file_count']}  src={r['source']}"
                )
        return 0

    runners = {
        "strategy": run_strategy_demo,
        "fundamental": run_fundamental_demo,
        "options": run_options_demo,
        "all": run_all_demos,
    }
    # Demos already archive by default; disable inner archive then pack once with CLI source tag
    result = runners[args.track](archive=False)
    packs = pack_jerry_demo_results(
        result if args.track == "all" else result,
        source=ArchiveSource(args.source),
    )

    payload = {k: v.model_dump(mode="json") for k, v in packs.items()}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=== archive packs ===")
        for track, pack in packs.items():
            print(f"\n[{track}]")
            print(f"  archive_id : {pack.archive_id}")
            print(f"  dir        : {pack.archive_dir}")
            print(f"  files      : {pack.file_count}")
            print(f"  manifest   : {pack.manifest_path}")
            if pack.manifest.missing_sources:
                print(f"  missing    : {pack.manifest.missing_sources}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
