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
        content_tokens = _keyword_tokens(result.content)
        overlap = len(query_tokens & content_tokens)
        file_name = str(result.metadata.get("file_name", ""))
        template_boost = 0.0
        if "投标文件" in query and "投标文件" in file_name:
            template_boost += 0.6
        if "施工组织设计" in query and "施工组织设计" in result.content:
            template_boost += 1.4
        if "施工组织设计" in query and "施工组织设计" not in result.content:
            template_boost -= 0.9
        for phrase in _important_phrases(query):
            if phrase in result.content:
                template_boost += 0.7
        if "第" in query and any(token in result.content for token in query_tokens):
            template_boost += 0.2
        return result.score + overlap * 0.25 + template_boost

    return sorted(results, key=combined_score, reverse=True)


def _important_phrases(query: str) -> list[str]:
    phrases = [
        "总体施工组织布置及规划",
        "主要工程项目的施工方案、方法与技术措施",
        "工期保证体系及保证措施",
        "工程质量管理体系及保证措施",
        "安全生产管理体系及保证措施",
        "环境保护、水土保持保证体系及保证措施",
        "文明施工、文物保护保证体系及保证措施",
        "项目风险预测与防范，事故应急预案",
    ]
    return [phrase for phrase in phrases if phrase in query]


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
    return retrieve_filtered(query=query, top_k=top_k, rerank=rerank)


def retrieve_filtered(
    query: str,
    top_k: int = 5,
    rerank: bool = True,
    document_type: str | None = None,
    specialty: str | None = None,
    tags: list[str] | None = None,
    chunk_ids: list[int] | None = None,
) -> list[RetrievalResult]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    candidate_limit = max(top_k * 5, top_k)
    query_embedding = format_vector(embed_text(query))
    filters = ["embedding IS NOT NULL"]
    params: list[object] = []
    if document_type:
        filters.append("metadata->>'document_type' = %s")
        params.append(document_type)
    if specialty:
        filters.append("metadata->>'specialty' = %s")
        params.append(specialty)
    if tags:
        filters.append("metadata->'tags' ?| %s")
        params.append(tags)
    if chunk_ids:
        filters.append("id = ANY(%s)")
        params.append(chunk_ids)
    where_clause = " AND ".join(filters)
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    id,
                    document_id,
                    content,
                    metadata,
                    embedding <-> %s::vector AS distance
                FROM knowledge_chunks
                WHERE {where_clause}
                ORDER BY embedding <-> %s::vector
                LIMIT %s
                """,
                [query_embedding, *params, query_embedding, candidate_limit],
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
        return rerank_by_keyword_overlap(query, results)[:top_k]
    return results[:top_k]
