from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class KnowledgeUploadResponse(BaseModel):
    document_id: int
    chunk_ids: list[int]
    file_path: str


class KnowledgeDocumentSummary(BaseModel):
    document_id: int
    file_name: str
    file_path: str | None = None
    file_type: str | None = None
    document_type: str | None = None
    specialty: str | None = None
    project_year: int | None = None
    tags: list[str] = []
    chunk_count: int
    created_at: str


class KnowledgeDocumentListResponse(BaseModel):
    documents: list[KnowledgeDocumentSummary]


class KnowledgeDocumentUpdateRequest(BaseModel):
    title: str
    document_type: str | None = None
    specialty: str | None = None
    project_year: int | None = None
    tags: list[str] = []


class KnowledgeDeleteResponse(BaseModel):
    ok: bool = True


class KnowledgeSearchResult(BaseModel):
    chunk_id: int
    document_id: int | None
    content: str
    metadata: dict[str, Any]
    score: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeSearchResult]
