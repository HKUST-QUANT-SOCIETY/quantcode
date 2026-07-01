"""
QuantCode 业务 schemas — 基本面组（fundamental group）

Owner: 用户（Lead）

业务 schema 作为 ComposeTask[TIn, TOut] 的类型参数：
- ResearchSpec → ComposeTask[ResearchSpec, ResearchResult]
- PITQuery → ComposeTask[PITQuery, PITResult]
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# ResearchSpec — 研报生成的输入规格
# ---------------------------------------------------------------------------

class TargetType(StrEnum):
    """研究目标类型"""
    COMPANY  = "company"   # 个股研究
    INDUSTRY = "industry"  # 行业研究
    MACRO    = "macro"     # 宏观研究


class SectionType(StrEnum):
    """研报章节类型（中金风格）"""
    OVERVIEW            = "overview"             # 公司概览
    BUSINESS            = "business"             # 业务分析
    FINANCIALS          = "financials"           # 财务分析
    VALUATION           = "valuation"            # 估值
    RISKS               = "risks"                # 风险提示
    INDUSTRY_COMPARISON = "industry_comparison"  # 行业对比


class ResearchSpec(BaseModel):
    """
    研报生成任务的输入规格。

    作为 ComposeTask[ResearchSpec, ResearchResult].input 使用。
    fundamental Compose 流: fundamental:brainstorm -> fetch -> extract ->
                           dcf -> draft -> render -> review -> publish
    """
    # --- 研究目标 ---------------------------------------------------------
    target_type: TargetType
    target_identifier: str = Field(
        description="公司用 ticker（如 2097.HK），行业用代码，宏观用主题字符串"
    )
    target_name: str | None = Field(
        default=None,
        description="可选的人类可读名称（如'蜜雪冰城'）"
    )

    # --- 时点约束 ---------------------------------------------------------
    as_of_date: date = Field(
        description="研报时点（所有引用数据必须 published_at <= as_of_date）"
    )

    # --- 研究问题 ---------------------------------------------------------
    research_questions: list[str] = Field(
        min_length=1,
        description="研究员关心的具体问题清单，如 ['2023 年收入增长驱动力？', '估值合理性？']"
    )

    # --- 章节要求 ---------------------------------------------------------
    sections: list[SectionType] = Field(
        default=[
            SectionType.OVERVIEW,
            SectionType.BUSINESS,
            SectionType.FINANCIALS,
            SectionType.VALUATION,
            SectionType.RISKS,
        ],
        description="要生成的章节（默认 5 章节，中金标准结构）"
    )

    # --- 输出格式 ---------------------------------------------------------
    output_format: str = Field(
        default="pdf",
        pattern=r"^(pdf|markdown|both)$",
        description="最终产物格式"
    )

    # --- PIT-RAG 检索结果（由 pit-rag skill 填充） ----------------------
    retrieval_result: PITResult | None = Field(
        default=None,
        description="pit-rag skill 返回的检索结果，fundamental:fetch 填充"
    )


class ResearchResult(BaseModel):
    """
    研报生成任务的输出。

    作为 ComposeTask[ResearchSpec, ResearchResult].output 使用。
    """
    pdf_path: str | None = Field(
        default=None,
        description="生成的 PDF 文件路径（如 artifacts/research/2097HK-2026-06-27.pdf）"
    )
    markdown_path: str | None = Field(
        default=None,
        description="生成的 Markdown 文件路径（如 artifacts/research/2097HK-2026-06-27.md）"
    )
    sections_generated: list[SectionType] = Field(
        default_factory=list,
        description="实际生成的章节列表"
    )
    citations_count: int = Field(
        default=0,
        ge=0,
        description="引用文献数量"
    )
    render_time_ms: int | None = Field(
        default=None,
        ge=0,
        description="Typst 渲染耗时（毫秒）"
    )
    word_count: int | None = Field(
        default=None,
        ge=0,
        description="正文字数（不含引用）"
    )

    @field_validator("pdf_path", "markdown_path")
    @classmethod
    def _check_path_exists_if_set(cls, v: str | None) -> str | None:
        if v:
            # TODO: 实际实现时检查文件是否存在
            # from pathlib import Path
            # if not Path(v).exists():
            #     raise ValueError(f"file not found: {v}")
            pass
        return v


# ---------------------------------------------------------------------------
# PITQuery & PITResult — Point-in-Time RAG
# ---------------------------------------------------------------------------

class CorpusType(StrEnum):
    """检索语料类型"""
    RESEARCH_REPORTS = "research_reports"  # 券商研报
    ANNOUNCEMENTS    = "announcements"     # 公告
    EARNINGS_CALLS   = "earnings_calls"    # 业绩电话会
    NEWS             = "news"              # 新闻
    ALL              = "all"               # 全部


class PITQuery(BaseModel):
    """
    Point-in-time RAG 检索查询。

    作为 ComposeTask[PITQuery, PITResult].input 使用。
    fundamental:fetch skill 调用 pit-rag skill 时传递。
    """
    query: str = Field(
        min_length=1,
        description="自然语言研究问题（如'蜜雪冰城 2023 年度财务分析'）"
    )
    as_of_date: date = Field(
        description="检索时点（所有返回文档 published_at <= as_of_date）"
    )
    corpus: list[CorpusType] = Field(
        default=[CorpusType.ALL],
        description="限定语料范围"
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="召回文档数量"
    )


class PITDocument(BaseModel):
    """PIT-RAG 返回的一个文档"""
    id: str = Field(description="文档唯一 ID")
    source: str = Field(description="来源（如'中金公司'）")
    title: str | None = Field(default=None, description="文档标题")
    published_at: date = Field(description="发布日期")
    snippet: str = Field(description="相关片段（摘要）")
    score: float = Field(ge=0, le=1, description="相关性得分")
    url: str | None = Field(default=None, description="原文链接")


class PITResult(BaseModel):
    """
    Point-in-time RAG 检索结果。

    作为 ComposeTask[PITQuery, PITResult].output 使用。

    关键约束（runner 验收）：
        for doc in result.documents:
            assert doc.published_at <= query.as_of_date
    """
    query: str = Field(description="原始查询")
    as_of_date: date = Field(description="检索时点")
    documents: list[PITDocument] = Field(
        default_factory=list,
        description="返回的文档列表（已按 score 降序排列）"
    )
    total_candidates: int = Field(
        default=0,
        ge=0,
        description="召回候选总数（时点过滤前）"
    )
    filtered_count: int = Field(
        default=0,
        ge=0,
        description="时点过滤掉的文档数量（lookahead bias）"
    )
    retrieval_time_ms: int = Field(
        default=0,
        ge=0,
        description="检索耗时（毫秒）"
    )

    @field_validator("documents")
    @classmethod
    def _check_no_lookahead(cls, docs: list[PITDocument], info) -> list[PITDocument]:
        """验收：所有文档 published_at <= as_of_date"""
        as_of = info.data.get("as_of_date")
        if as_of:
            leaked = [d.id for d in docs if d.published_at > as_of]
            if leaked:
                raise ValueError(
                    f"lookahead bias detected: {len(leaked)} docs published after "
                    f"{as_of}: {leaked[:5]}"
                )
        return docs
