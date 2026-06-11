from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class KnowledgeUploadResponse(BaseModel):
    document_id: int
    chunk_ids: list[int]
    file_path: str
    indexing_status: str = "indexed"
    extraction_message: str = ""


class KnowledgeDocumentSummary(BaseModel):
    document_id: int
    file_name: str
    file_path: str | None = None
    file_type: str | None = None
    project_type: str | None = None
    document_type: str | None = None
    document_category: str | None = None
    specialty: str | None = None
    volume: str | None = None
    region: str | None = None
    project_year: int | None = None
    owner_type: str | None = None
    owner_name: str | None = None
    certificate_type: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    sensitivity: str | None = None
    usage_scope: str | None = None
    verified_status: str | None = None
    image_insertable: bool | None = None
    tags: list[str] = []
    ingestion_mode: str | None = None
    indexing_status: str | None = None
    extraction_message: str | None = None
    chunk_count: int
    created_at: str


class KnowledgeDocumentListResponse(BaseModel):
    documents: list[KnowledgeDocumentSummary]


class KnowledgeDocumentPreviewResponse(BaseModel):
    document_id: int
    file_name: str
    file_type: str | None = None
    preview_type: str
    content: str = ""
    preview_url: str | None = None
    download_url: str | None = None
    expires_in: int = 900
    indexing_status: str | None = None
    extraction_message: str | None = None


class KnowledgeDocumentUpdateRequest(BaseModel):
    title: str
    project_type: str | None = None
    document_type: str | None = None
    document_category: str | None = None
    specialty: str | None = None
    volume: str | None = None
    region: str | None = None
    project_year: int | None = None
    owner_type: str | None = None
    owner_name: str | None = None
    certificate_type: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    sensitivity: str | None = None
    usage_scope: str | None = None
    verified_status: str | None = None
    image_insertable: bool | None = None
    tags: list[str] | None = None


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
