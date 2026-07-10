"""Tests for fundamental group tools — Day 4 刘炽。"""
from __future__ import annotations

import importlib

import pytest

from schemas.fundamental import PITResult, ResearchResult
from tools.registry import registry

import tools.fundamental._register  # noqa: F401

EXPECTED = {
    "pit_rag_search",
    "extract_financial",
    "dcf_valuation",
    "render_report",
}


@pytest.fixture(autouse=True)
def _ensure_registered():
    importlib.reload(tools.fundamental._register)
    yield


def test_fundamental_tools_registered():
    assert EXPECTED.issubset(set(registry.list_ids()))


def test_fundamental_allowlist():
    assert {t.id for t in registry.get_tools_for_group("fundamental")} == EXPECTED


def test_pit_rag_filters_lookahead():
    result = registry.call(
        "pit_rag_search",
        {
            "query": "蜜雪冰城 财务",
            "as_of_date": "2025-01-01",
            "top_k": 10,
        },
    )
    validated = PITResult.model_validate(result)
    assert validated.filtered_count >= 1
    assert all(d.published_at <= validated.as_of_date for d in validated.documents)
    assert "DOC-LEAK-2026" not in {d.id for d in validated.documents}


def test_extract_dcf_render_pipeline():
    from tools.registry import PROJECT_ROOT

    pit = registry.call(
        "pit_rag_search",
        {"query": "蜜雪冰城 财务", "as_of_date": "2025-01-01", "top_k": 10},
    )
    fin = registry.call(
        "extract_financial",
        {
            "target_identifier": "2097.HK",
            "as_of_date": "2025-01-01",
            "documents": pit["documents"],
        },
    )
    assert fin["fcf_ttm"] > 0

    dcf = registry.call(
        "dcf_valuation",
        {
            "target_identifier": "2097.HK",
            "fcf_ttm": fin["fcf_ttm"],
            "shares_outstanding_m": fin["shares_outstanding_m"],
        },
    )
    assert dcf["fair_value_per_share"] > 0

    report = registry.call(
        "render_report",
        {
            "target_identifier": "2097.HK",
            "target_name": "蜜雪冰城",
            "as_of_date": "2025-01-01",
            "research_questions": ["收入增长驱动力？"],
            "fair_value_per_share": dcf["fair_value_per_share"],
            "citations_count": 12,
            "use_typst": True,
            "financials": fin,
            "dcf": dcf,
            "documents": pit["documents"],
            "pit_filtered_count": pit["filtered_count"],
        },
    )
    validated = ResearchResult.model_validate(
        {
            k: v
            for k, v in report.items()
            if k not in ("typst_used", "markdown_filled")
        }
    )
    assert validated.markdown_path
    assert len(validated.sections_generated) >= 5
    assert validated.citations_count >= 4
    assert report.get("markdown_filled") is True
    md = (PROJECT_ROOT / validated.markdown_path).read_text(encoding="utf-8")
    assert "Fair value" in md or "fair value" in md.lower()
    assert "FCF TTM" in md
    assert "DOC-CICC-2023-AR" in md or "中金" in md
    assert "Stub content for" not in md


def test_load_fundamental_compose_skill():
    from tools.skills.loader import load_skill

    text = load_skill("fundamental-compose", group="fundamental")
    assert "pit_rag_search" in text
