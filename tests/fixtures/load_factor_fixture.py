"""Load factor backtest fixture as FactorReport."""
from __future__ import annotations

import json
from pathlib import Path

from schemas import FactorReport

FIXTURE_PATH = Path(__file__).parent / "factor_backtest_result.json"


def load_factor_backtest_fixture() -> FactorReport:
    return FactorReport.model_validate(json.loads(FIXTURE_PATH.read_text()))
