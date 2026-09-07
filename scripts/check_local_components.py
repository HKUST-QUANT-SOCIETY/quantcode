#!/usr/bin/env python3
"""Report local canonical component checkouts without importing or executing them."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "local_components.yaml"


def inspect(config: Path = CONFIG) -> dict:
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    rows = []
    for component_id, item in (data.get("components") or {}).items():
        path = str(item.get("local_path") or "").strip()
        resolved = Path(path).expanduser() if path else None
        rows.append({
            "id": component_id,
            "canonical_repo": item.get("canonical_repo"),
            "local_path": path or None,
            "status": "LOCAL_READY" if resolved and resolved.is_dir() else "LOCAL_CHECKOUT_REQUIRED",
            "future_api_env": item.get("future_api_env"),
        })
    return {"mode": data.get("mode", "local_checkout"), "prelearn_from": data.get("prelearn_from"), "components": rows}


if __name__ == "__main__":
    print(json.dumps(inspect(), ensure_ascii=False, indent=2))
