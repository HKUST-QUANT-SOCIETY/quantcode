"""extract_financial tool — 从语料/公司标识提取财务摘要（stub）。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from tools.registry import ToolDef


class ExtractFinancialArgs(BaseModel):
    target_identifier: str = Field(min_length=1, examples=["2097.HK"])
    as_of_date: date
    documents: list[dict] = Field(
        default_factory=list,
        description="可选：pit_rag_search 返回的 documents",
    )


def extract_financial_execute(args: ExtractFinancialArgs, ctx: dict) -> dict:
    # Deterministic stub financials keyed by ticker hash
    seed = sum(ord(c) for c in args.target_identifier) % 17
    revenue = 10_000 + seed * 500
    ebit = round(revenue * (0.12 + seed * 0.005), 2)
    net_income = round(ebit * 0.75, 2)
    fcf = round(net_income * 0.9, 2)
    citations = [d.get("id") for d in args.documents if d.get("id")][:5]
    return {
        "target_identifier": args.target_identifier,
        "as_of_date": args.as_of_date.isoformat(),
        "currency": "CNY",
        "revenue_ttm": float(revenue),
        "ebit_ttm": float(ebit),
        "net_income_ttm": float(net_income),
        "fcf_ttm": float(fcf),
        "shares_outstanding_m": 800.0 + seed,
        "source_doc_ids": citations,
        "notes": "stub financial extract from PIT corpus / ticker seed",
    }


extract_financial_tool = ToolDef(
    id="extract_financial",
    description=(
        "Extract structured financials for a company as-of a date (stub). "
        "Input: target_identifier, as_of_date, optional documents from pit_rag_search. "
        "Returns revenue/ebit/net_income/fcf summary JSON."
    ),
    schema=ExtractFinancialArgs,
    execute=extract_financial_execute,
)

__all__ = ["extract_financial_tool", "ExtractFinancialArgs", "extract_financial_execute"]
