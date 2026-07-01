"""Tiny deterministic sample model for Day 1 PR metadata tests."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StockFeatures:
    ticker: str
    pb: float
    roe_ttm: float
    market_cap: float


def score_stock(features: StockFeatures) -> float:
    """Return a simple PB/ROE score; higher is better."""
    valuation_score = 1 / max(features.pb, 0.01)
    quality_score = features.roe_ttm
    size_penalty = min(features.market_cap / 1_000_000_000_000, 1.0) * 0.1
    return valuation_score * 0.45 + quality_score * 0.55 - size_penalty


def rank_stocks(rows: list[StockFeatures]) -> list[tuple[str, float]]:
    """Rank stocks by descending sample score."""
    scored = [(row.ticker, score_stock(row)) for row in rows]
    return sorted(scored, key=lambda item: item[1], reverse=True)


if __name__ == "__main__":
    sample = [
        StockFeatures("000001.SZ", pb=0.82, roe_ttm=0.11, market_cap=280_000_000_000),
        StockFeatures("600519.SH", pb=8.5, roe_ttm=0.32, market_cap=2_100_000_000_000),
        StockFeatures("300750.SZ", pb=5.2, roe_ttm=0.18, market_cap=900_000_000_000),
    ]
    for ticker, score in rank_stocks(sample):
        print(f"{ticker}: {score:.4f}")
