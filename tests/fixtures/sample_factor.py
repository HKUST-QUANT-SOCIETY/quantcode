"""Day 1 sample factor fixture for factor:evaluation.

This fixture verifies the contract path only. It is not an investment claim.
"""
from __future__ import annotations

from typing import Any


def pb_roe_combo(panel: Any) -> Any:
    """Return a simple PB-ROE combination factor."""
    pb = panel["pb"]
    if hasattr(pb, "replace"):
        pb = pb.replace(0, float("nan"))
    return panel["roe_ttm"] / pb

