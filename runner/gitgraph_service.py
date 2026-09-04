"""GitGraph baseline and dependency-diff helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class GitGraphBaselineStore:
    """Small atomic JSON baseline store used by background GitHub sync jobs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, snapshot: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def changed(self, key: str, value: Any) -> tuple[Any, Any] | None:
        old = self.load().get(key)
        return None if old == value else (old, value)


def dependency_changes(
    old: dict[str, str], new: dict[str, str]
) -> list[dict[str, str | None]]:
    """Return deterministic old/new rows for added, removed, or changed packages."""
    changes = []
    for name in sorted(set(old) | set(new)):
        if old.get(name) != new.get(name):
            changes.append({"package": name, "old_value": old.get(name), "new_value": new.get(name)})
    return changes


__all__ = ["GitGraphBaselineStore", "dependency_changes"]
