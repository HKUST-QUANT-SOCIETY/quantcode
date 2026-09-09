"""Initialize or update the Server C authoritative shared Memory store.

This is an administrator operation. It writes only governed platform references
and capability cards; it never imports member-private state or local workspaces.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from runner.memory.service import MemoryService
from runner.distill.cards import distill_cards_to_memory, load_cards


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    service = MemoryService(root / ".quantcode" / "memory.db", root=root)
    service.write(
        scope="global", type="reference", key="quantcode-platform-contract",
        body=("# QuantCode platform contract\n\n"
              "Use registered capabilities, preserve source/environment/result status, "
              "and keep group knowledge within the server-enforced Memory scope."),
    )
    written = distill_cards_to_memory(service, load_cards())
    print({"status": "INITIALIZED", "root": str(root), "capability_cards": len(written)})


if __name__ == "__main__":
    main()
