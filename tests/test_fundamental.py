"""Tests for fundamental group schemas (ResearchSpec / PITQuery / PITResult)."""
from __future__ import annotations

import pytest
from datetime import date
from pydantic import ValidationError

from schemas.fundamental import (
    CorpusType,
    PITDocument,
    PITQuery,
    PITResult,
    ResearchResult,
    ResearchSpec,
    SectionType,
    TargetType,
)


# ---------------------------------------------------------------------------
# ResearchSpec tests
# ---------------------------------------------------------------------------

def test_research_spec_valid():
    spec = ResearchSpec(
        target_type=TargetType.COMPANY,
        target_identifier="2097.HK",
        target_name="蜜雪冰城",
        as_of_date=date(2024, 3, 15),
        research_questions=["2023 年收入增长驱动力？"],
    )
    assert spec.target_identifier == "2097.HK"
    assert len(spec.research_questions) == 1
    assert len(spec.sections) == 5  # 默认 5 章节


def test_research_spec_requires_at_least_one_question():
    with pytest.raises(ValidationError, match="at least 1 item"):
        ResearchSpec(
            target_type=TargetType.COMPANY,
            target_identifier="2097.HK",
            as_of_date=date(2024, 3, 15),
            research_questions=[],  # ❌ 空列表
        )


def test_research_spec_custom_sections():
    spec = ResearchSpec(
        target_type=TargetType.INDUSTRY,
        target_identifier="餐饮",
        as_of_date=date(2024, 3, 15),
        research_questions=["行业增速？"],
        sections=[SectionType.OVERVIEW, SectionType.INDUSTRY_COMPARISON],
    )
    assert len(spec.sections) == 2


# ---------------------------------------------------------------------------
# PITQuery tests
# ---------------------------------------------------------------------------

def test_pit_query_valid():
    query = PITQuery(
        query="蜜雪冰城 2023 年度财务",
        as_of_date=date(2024, 3, 15),
        corpus=[CorpusType.RESEARCH_REPORTS, CorpusType.ANNOUNCEMENTS],
        top_k=20,
    )
    assert query.top_k == 20
    assert len(query.corpus) == 2


def test_pit_query_default_corpus():
    query = PITQuery(
        query="test",
        as_of_date=date(2024, 1, 1),
    )
    assert query.corpus == [CorpusType.ALL]
    assert query.top_k == 10


def test_pit_query_top_k_bounds():
    with pytest.raises(ValidationError):
        PITQuery(
            query="test",
            as_of_date=date(2024, 1, 1),
            top_k=0,  # ❌ 必须 >= 1
        )

    with pytest.raises(ValidationError):
        PITQuery(
            query="test",
            as_of_date=date(2024, 1, 1),
            top_k=101,  # ❌ 必须 <= 100
        )


# ---------------------------------------------------------------------------
# PITResult lookahead bias detection
# ---------------------------------------------------------------------------

def test_pit_result_no_lookahead_valid():
    result = PITResult(
        query="蜜雪冰城财务",
        as_of_date=date(2024, 3, 15),
        documents=[
            PITDocument(
                id="doc1",
                source="中金",
                published_at=date(2024, 2, 20),
                snippet="...",
                score=0.9,
            ),
            PITDocument(
                id="doc2",
                source="港交所",
                published_at=date(2024, 3, 1),
                snippet="...",
                score=0.8,
            ),
        ],
        total_candidates=50,
        filtered_count=10,
        retrieval_time_ms=450,
    )
    assert len(result.documents) == 2


def test_pit_result_lookahead_detected():
    """Validator should catch docs published after as_of_date"""
    with pytest.raises(ValidationError, match="lookahead bias detected"):
        PITResult(
            query="test",
            as_of_date=date(2024, 3, 15),
            documents=[
                PITDocument(
                    id="ok",
                    source="中金",
                    published_at=date(2024, 2, 20),
                    snippet="...",
                    score=0.9,
                ),
                PITDocument(
                    id="leak",
                    source="港交所",
                    published_at=date(2024, 4, 1),  # ❌ 穿越
                    snippet="...",
                    score=0.8,
                ),
            ],
            total_candidates=2,
        )


def test_pit_result_boundary_case():
    """published_at == as_of_date should be allowed"""
    result = PITResult(
        query="test",
        as_of_date=date(2024, 3, 15),
        documents=[
            PITDocument(
                id="boundary",
                source="test",
                published_at=date(2024, 3, 15),  # ✅ 边界值
                snippet="...",
                score=0.9,
            ),
        ],
        total_candidates=1,
    )
    assert len(result.documents) == 1


# ---------------------------------------------------------------------------
# ResearchResult tests
# ---------------------------------------------------------------------------

def test_research_result_valid():
    result = ResearchResult(
        pdf_path="artifacts/research/2097HK-2024-03-15.pdf",
        sections_generated=[
            SectionType.OVERVIEW,
            SectionType.BUSINESS,
            SectionType.FINANCIALS,
        ],
        citations_count=23,
        render_time_ms=1840,
        word_count=5200,
    )
    assert result.citations_count == 23
    assert len(result.sections_generated) == 3


def test_research_result_minimal():
    """Minimal valid instance"""
    result = ResearchResult()
    assert result.citations_count == 0
    assert result.sections_generated == []


# ---------------------------------------------------------------------------
# Integration with ComposeTask (type checking only, no runtime)
# ---------------------------------------------------------------------------

def test_research_spec_as_compose_task_input():
    """Type hint check: ComposeTask[ResearchSpec, ResearchResult] should be valid"""
    from schemas import ComposeTask, GroupName

    spec = ResearchSpec(
        target_type=TargetType.COMPANY,
        target_identifier="2097.HK",
        as_of_date=date(2024, 3, 15),
        research_questions=["test"],
    )

    task = ComposeTask[ResearchSpec, ResearchResult](
        task_id="T3",
        session_id="S0123456789abcdef",
        root_task_id="T3",
        group=GroupName.FUNDAMENTAL,
        summary="Generate research report",
        input=spec,
    )

    assert task.input.target_identifier == "2097.HK"
    assert task.output is None  # not filled yet


def test_pit_query_as_compose_task_input():
    """Type hint check: ComposeTask[PITQuery, PITResult] should be valid"""
    from schemas import ComposeTask, GroupName

    query = PITQuery(
        query="test",
        as_of_date=date(2024, 3, 15),
    )

    task = ComposeTask[PITQuery, PITResult](
        task_id="T3.1",
        session_id="S0123456789abcdef",
        root_task_id="T3",
        parent_task_id="T3",
        depth=1,
        group=GroupName.FUNDAMENTAL,
        summary="PIT-RAG retrieval",
        input=query,
    )

    assert task.input.query == "test"
