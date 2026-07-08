"""Shared utilities for the routing package."""

from __future__ import annotations

from pathlib import Path

__all__ = ["_repo_root"]


def _repo_root() -> Path:
    """Walk up from this file until we find .git or pyproject.toml."""
    here = Path(__file__).resolve().parent
    for _ in range(6):
        if (here / ".git").exists() or (here / "pyproject.toml").exists():
            return here
        here = here.parent
    return Path.cwd()
