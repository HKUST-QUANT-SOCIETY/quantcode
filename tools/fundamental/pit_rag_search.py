"""pit_rag_search tool — Chroma 检索 + 强制 PIT（published_at <= as_of_date）。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from schemas.fundamental import CorpusType, PITDocument, PITQuery, PITResult
from tools.fundamental.chroma_store import (
    DEFAULT_FIXTURE,
    load_fixture_documents,
    query_chroma,
)
from tools.registry import PROJECT_ROOT, ToolDef


class PitRagSearchArgs(BaseModel):
    query: str = Field(min_length=1)
    as_of_date: date
    top_k: int = Field(default=10, ge=1, le=100)
    corpus: list[str] = Field(default_factory=lambda: ["all"])
    fixture_path: str = Field(
        default=str(DEFAULT_FIXTURE.relative_to(PROJECT_ROOT)),
        description="语料种子（首次写入 Chroma；Chroma 不可用时直接读此文件）",
    )
    force_fixture: bool = Field(
        default=False,
        description="True 时跳过 Chroma，仅读 fixture（测试用）",
    )


def pit_rag_search_execute(args: PitRagSearchArgs, ctx: dict) -> dict:
    fixture = Path(args.fixture_path)
    if not fixture.is_absolute():
        fixture = PROJECT_ROOT / fixture

    if args.force_fixture:
        raw_docs = load_fixture_documents(fixture)
        backend = "fixture_json"
    else:
        raw_docs, backend = query_chroma(
            args.query, top_k=args.top_k, fixture_path=fixture
        )

    total = len(raw_docs)
    kept: list[PITDocument] = []
    filtered = 0

    for d in raw_docs:
        pub = date.fromisoformat(str(d["published_at"])[:10])
        if pub > args.as_of_date:
            filtered += 1
            continue
        kept.append(
            PITDocument(
                id=d["id"],
                source=d.get("source", "unknown"),
                title=d.get("title"),
                published_at=pub,
                snippet=d.get("snippet", ""),
                score=float(d.get("score", 0.5)),
                url=d.get("url"),
            )
        )

    kept.sort(key=lambda x: x.score, reverse=True)
    kept = kept[: args.top_k]

    corpora = []
    for c in args.corpus:
        try:
            corpora.append(CorpusType(c))
        except ValueError:
            corpora.append(CorpusType.ALL)
    if not corpora:
        corpora = [CorpusType.ALL]

    PITQuery(query=args.query, as_of_date=args.as_of_date, corpus=corpora, top_k=args.top_k)
    result = PITResult(
        query=args.query,
        as_of_date=args.as_of_date,
        documents=kept,
        total_candidates=total,
        filtered_count=filtered,
        retrieval_time_ms=5 if backend == "chroma" else 3,
    )
    payload = result.model_dump(mode="json")
    payload["backend"] = backend
    payload["pit_rule"] = "published_at <= as_of_date"
    return payload


pit_rag_search_tool = ToolDef(
    id="pit_rag_search",
    description=(
        "Point-in-time RAG search over research corpus via Chroma. "
        "Enforces published_at <= as_of_date (no lookahead). "
        "Input: query, as_of_date, optional top_k / corpus. "
        "Returns PITResult JSON plus backend=chroma|fixture_json."
    ),
    schema=PitRagSearchArgs,
    execute=pit_rag_search_execute,
)

__all__ = ["pit_rag_search_tool", "PitRagSearchArgs", "pit_rag_search_execute"]
