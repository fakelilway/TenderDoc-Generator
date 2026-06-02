from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class KnowledgeUploadResponse(BaseModel):
    document_id: int
    chunk_ids: list[int]
    file_path: str


class KnowledgeSearchResult(BaseModel):
    chunk_id: int
    document_id: int | None
    content: str
    metadata: dict[str, Any]
    score: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeSearchResult]
