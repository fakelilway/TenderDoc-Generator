from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from sentence_transformers import CrossEncoder

from core.config import settings
from rag.embeddings import embed_text
from rag.vector_store import _connect, format_vector


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: int
    document_id: int | None
    content: str
    metadata: dict
    distance: float
    score: float


def _keyword_tokens(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text.lower()))


def rerank_by_keyword_overlap(
    query: str,
    results: Iterable[RetrievalResult],
) -> list[RetrievalResult]:
    query_tokens = _keyword_tokens(query)
    if not query_tokens:
        return sorted(results, key=lambda result: result.score, reverse=True)

    def combined_score(result: RetrievalResult) -> float:
        overlap = len(query_tokens & _keyword_tokens(result.content))
        return result.score + overlap * 0.25

    return sorted(results, key=combined_score, reverse=True)


def rerank_with_cross_encoder(
    query: str,
    results: Iterable[RetrievalResult],
    model_name: str | None = None,
) -> list[RetrievalResult]:
    results = list(results)
    if not results:
        return []

    model = CrossEncoder(model_name or settings.rerank_model)
    pairs = [(query, result.content) for result in results]
    scores = model.predict(pairs)
    return [
        result
        for result, _score in sorted(
            zip(results, scores), key=lambda item: float(item[1]), reverse=True
        )
    ]


def retrieve(query: str, top_k: int = 5, rerank: bool = True) -> list[RetrievalResult]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    query_embedding = format_vector(embed_text(query))
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    document_id,
                    content,
                    metadata,
                    embedding <-> %s::vector AS distance
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <-> %s::vector
                LIMIT %s
                """,
                (query_embedding, query_embedding, top_k),
            )
            rows = cursor.fetchall()

    results = [
        RetrievalResult(
            chunk_id=row[0],
            document_id=row[1],
            content=row[2],
            metadata=row[3] or {},
            distance=float(row[4]),
            score=1.0 / (1.0 + float(row[4])),
        )
        for row in rows
    ]
    if rerank:
        return rerank_by_keyword_overlap(query, results)
    return results
