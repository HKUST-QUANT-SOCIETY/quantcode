"""pit_rag_search tool — 时点安全语料检索（fixture stub，强制 PIT）。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from schemas.fundamental import CorpusType, PITDocument, PITQuery, PITResult
from tools.registry import PROJECT_ROOT, ToolDef

_DEFAULT_FIXTURE = "tests/fixtures/pit_corpus_sample.json"


class PitRagSearchArgs(BaseModel):
    query: str = Field(min_length=1)
    as_of_date: date
    top_k: int = Field(default=10, ge=1, le=100)
    corpus: list[str] = Field(default_factory=lambda: ["all"])
    fixture_path: str = Field(
        default=_DEFAULT_FIXTURE,
        description="本地语料 fixture（Day4 stub；Day4+/§8 可换 Chroma）",
    )


def _load_corpus(path: Path) -> list[dict]:
    if not path.exists():
        return [
            {
                "id": "DOC-FALLBACK-1",
                "source": "stub",
                "title": "Fallback research note",
                "published_at": "2024-01-01",
                "snippet": "No fixture found; returning fallback doc.",
                "score": 0.5,
                "url": None,
            }
        ]
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("documents", data if isinstance(data, list) else []))


def pit_rag_search_execute(args: PitRagSearchArgs, ctx: dict) -> dict:
    fixture = Path(args.fixture_path)
    if not fixture.is_absolute():
        fixture = PROJECT_ROOT / fixture

    raw_docs = _load_corpus(fixture)
    total = len(raw_docs)
    kept: list[PITDocument] = []
    filtered = 0
    q_lower = args.query.lower()

    for d in raw_docs:
        pub = date.fromisoformat(str(d["published_at"])[:10])
        if pub > args.as_of_date:
            filtered += 1
            continue
        text = f"{d.get('title', '')} {d.get('snippet', '')}".lower()
        score = float(d.get("score", 0.5))
        if q_lower and any(tok in text for tok in q_lower.split() if len(tok) > 1):
            score = min(score + 0.2, 1.0)
        kept.append(
            PITDocument(
                id=d["id"],
                source=d.get("source", "unknown"),
                title=d.get("title"),
                published_at=pub,
                snippet=d.get("snippet", ""),
                score=score,
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

    # validate via PITQuery/PITResult contracts
    PITQuery(query=args.query, as_of_date=args.as_of_date, corpus=corpora, top_k=args.top_k)
    result = PITResult(
        query=args.query,
        as_of_date=args.as_of_date,
        documents=kept,
        total_candidates=total,
        filtered_count=filtered,
        retrieval_time_ms=3,
    )
    return result.model_dump(mode="json")


pit_rag_search_tool = ToolDef(
    id="pit_rag_search",
    description=(
        "Point-in-time RAG search over research corpus. "
        "Enforces published_at <= as_of_date (no lookahead). "
        "Input: query, as_of_date, optional top_k / corpus / fixture_path. "
        "Returns PITResult JSON."
    ),
    schema=PitRagSearchArgs,
    execute=pit_rag_search_execute,
)

__all__ = ["pit_rag_search_tool", "PitRagSearchArgs", "pit_rag_search_execute"]
