"""Chroma-backed PIT corpus store for fundamental pit_rag_search.

Day5 requirement: pit_rag uses real Chroma API (not only JSON fixture reads).
Collection is seeded from ``tests/fixtures/pit_corpus_sample.json`` on first use
so local/CI can run without an external Chroma server.

Backend flags returned to callers:
- ``chroma`` — queried via chromadb PersistentClient
- ``fixture_json`` — chromadb unavailable; fell back to fixture file
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.registry import PROJECT_ROOT

DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "pit_corpus_sample.json"
CHROMA_DIR = PROJECT_ROOT / ".quantcode" / "chroma_pit"
COLLECTION_NAME = "fundamental_pit_corpus"


def load_fixture_documents(fixture_path: Path | None = None) -> list[dict[str, Any]]:
    path = fixture_path or DEFAULT_FIXTURE
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("documents", data if isinstance(data, list) else []))


def _try_import_chroma():
    try:
        import chromadb  # type: ignore
        from chromadb.config import Settings  # type: ignore

        return chromadb, Settings
    except Exception:
        return None, None


def ensure_chroma_collection(
    *,
    fixture_path: Path | None = None,
    persist_dir: Path | None = None,
    force_reseed: bool = False,
) -> tuple[Any | None, str]:
    """Return (collection, backend). collection is None if chroma unavailable."""
    chromadb, Settings = _try_import_chroma()
    if chromadb is None:
        return None, "fixture_json"

    persist = persist_dir or CHROMA_DIR
    persist.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(persist),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    docs = load_fixture_documents(fixture_path)
    if force_reseed and collection.count() > 0:
        # wipe by recreating
        client.delete_collection(COLLECTION_NAME)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    if collection.count() == 0 and docs:
        ids = [str(d["id"]) for d in docs]
        documents = [
            f"{d.get('title', '')}\n{d.get('snippet', '')}".strip() for d in docs
        ]
        metadatas = [
            {
                "source": str(d.get("source", "unknown")),
                "published_at": str(d.get("published_at", ""))[:10],
                "title": str(d.get("title") or ""),
                "url": str(d.get("url") or ""),
                "score": float(d.get("score") or 0.5),
            }
            for d in docs
        ]
        collection.add(ids=ids, documents=documents, metadatas=metadatas)

    return collection, "chroma"


def query_chroma(
    query: str,
    *,
    top_k: int = 10,
    fixture_path: Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Query Chroma; return (raw doc dicts, backend)."""
    collection, backend = ensure_chroma_collection(fixture_path=fixture_path)
    if collection is None:
        # fallback: plain fixture list
        return load_fixture_documents(fixture_path), "fixture_json"

    n = max(collection.count(), 1)
    result = collection.query(
        query_texts=[query or "research"],
        n_results=min(top_k * 3, n),  # over-fetch then PIT-filter
        include=["documents", "metadatas", "distances"],
    )
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    out: list[dict[str, Any]] = []
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if i < len(metadatas) else {}
        dist = distances[i] if i < len(distances) else 1.0
        # convert distance to a pseudo score in (0,1]
        score = max(0.0, min(1.0, 1.0 - float(dist) / 2.0))
        text = documents[i] if i < len(documents) else ""
        title = meta.get("title") or ""
        snippet = text
        if title and text.startswith(title):
            snippet = text[len(title) :].strip() or text
        out.append(
            {
                "id": doc_id,
                "source": meta.get("source", "unknown"),
                "title": title or None,
                "published_at": meta.get("published_at", "1970-01-01"),
                "snippet": snippet,
                "score": float(meta.get("score") or score),
                "url": meta.get("url") or None,
            }
        )
    return out, backend


__all__ = [
    "DEFAULT_FIXTURE",
    "CHROMA_DIR",
    "COLLECTION_NAME",
    "load_fixture_documents",
    "ensure_chroma_collection",
    "query_chroma",
]
