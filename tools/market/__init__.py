"""Market data tools — qs-cold staging read-only access (P-01, specs/data/SPEC.md).

Four tools: list_factors / load_factor_panel / load_returns / pool_browse.

- Backend: QS_DATA_BACKEND=staging (default) reads the Server A staging
  copy of the qs-cold factor pool from QS_DATA_STAGING_ROOT
  (default /srv/quant/data/migration-staging/...). Pure local-file reads —
  fail-closed: no network, no credentials.
- Unknown backends raise PermissionError/ValueError, never silently degrade
  (D1-A7).
- Tools return key + summary + stats only; big matrices stay in the
  FactorPanel contract object written to the Blackboard (SPEC §2.3).
"""
from tools.market._register import (
    list_factors_tool,
    load_factor_panel_tool,
    load_returns_tool,
    pool_browse_tool,
)

__all__ = [
    "list_factors_tool",
    "load_factor_panel_tool",
    "load_returns_tool",
    "pool_browse_tool",
]