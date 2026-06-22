from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from api.deps import _raise_http_error
from rag import retriever
from schemas.auth import UserProfile
from schemas.knowledge import (
    KnowledgeDeleteResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentPreviewResponse,
    KnowledgeDocumentSummary,
    KnowledgeDocumentUpdateRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeUploadResponse,
)
from services import auth_service, knowledge_service


router = APIRouter()


@router.post("/api/knowledge/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge(
    file: UploadFile = File(...),
    project_type: str | None = Form(None),
    document_type: str | None = Form(None),
    document_category: str | None = Form(None),
    specialty: str | None = Form(None),
    volume: str | None = Form(None),
    region: str | None = Form(None),
    project_year: int | None = Form(None),
    owner_type: str | None = Form(None),
    owner_name: str | None = Form(None),
    certificate_type: str | None = Form(None),
    valid_from: str | None = Form(None),
    valid_to: str | None = Form(None),
    sensitivity: str | None = Form(None),
    usage_scope: str | None = Form(None),
    verified_status: str | None = Form(None),
    image_insertable: bool | None = Form(None),
    tags: str | None = Form(None),
    ingestion_mode: str | None = Form(None),
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> KnowledgeUploadResponse:
    try:
        metadata_kwargs = {}
        for key, value in {
            "project_type": project_type,
            "document_type": document_type,
            "document_category": document_category,
            "specialty": specialty,
            "volume": volume,
            "region": region,
            "project_year": project_year,
            "owner_type": owner_type,
            "owner_name": owner_name,
            "certificate_type": certificate_type,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "sensitivity": sensitivity,
            "usage_scope": usage_scope,
            "verified_status": verified_status,
            "image_insertable": image_insertable,
        }.items():
            if value is not None:
                metadata_kwargs[key] = value
        parsed_tags = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]
        if parsed_tags:
            metadata_kwargs["tags"] = parsed_tags
        if ingestion_mode is not None:
            metadata_kwargs["ingestion_mode"] = ingestion_mode
        indexed = knowledge_service.index_uploaded_knowledge(
            file_bytes=await file.read(),
            filename=file.filename or "knowledge.txt",
            content_type=file.content_type,
            **metadata_kwargs,
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeUploadResponse(**indexed)


@router.get("/api/knowledge/documents", response_model=KnowledgeDocumentListResponse)
def list_knowledge_documents(
    limit: int = Query(200, ge=1, le=1000),
    category: str | None = Query(None),
    search: str | None = Query(None),
    categories: str | None = Query(None),
    exclude_categories: str | None = Query(None),
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> KnowledgeDocumentListResponse:
    def _split(value: str | None) -> list[str] | None:
        if not value:
            return None
        items = [item.strip() for item in value.split(",") if item.strip()]
        return items or None

    try:
        documents = knowledge_service.list_knowledge_documents(
            limit=limit,
            category=category,
            search=search,
            categories=_split(categories),
            exclude_categories=_split(exclude_categories),
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDocumentListResponse(
        documents=[KnowledgeDocumentSummary(**document) for document in documents]
    )


@router.get("/api/knowledge/category-counts")
def knowledge_category_counts(
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> dict[str, int]:
    try:
        return knowledge_service.count_documents_by_category()
    except Exception as error:
        _raise_http_error(error)


@router.patch(
    "/api/knowledge/documents/{document_id}",
    response_model=KnowledgeDocumentSummary,
)
def rename_knowledge_document(
    document_id: int,
    request: KnowledgeDocumentUpdateRequest,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> KnowledgeDocumentSummary:
    try:
        kwargs = {}
        for key in (
            "project_type",
            "document_type",
            "document_category",
            "specialty",
            "volume",
            "region",
            "project_year",
            "owner_type",
            "owner_name",
            "certificate_type",
            "valid_from",
            "valid_to",
            "sensitivity",
            "usage_scope",
            "verified_status",
            "image_insertable",
            "tags",
        ):
            value = getattr(request, key)
            if value is not None:
                kwargs[key] = value
        document = knowledge_service.rename_knowledge_document(
            document_id,
            request.title,
            **kwargs,
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDocumentSummary(**document)


@router.get(
    "/api/knowledge/documents/{document_id}/preview",
    response_model=KnowledgeDocumentPreviewResponse,
)
def preview_knowledge_document(
    document_id: int,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> KnowledgeDocumentPreviewResponse:
    try:
        preview = knowledge_service.get_knowledge_document_preview(document_id)
    except Exception as error:
        _raise_http_error(error)
    return KnowledgeDocumentPreviewResponse(**preview)


@router.delete(
    "/api/knowledge/documents/{document_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_document(
    document_id: int,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> KnowledgeDeleteResponse:
    try:
        knowledge_service.delete_knowledge_document(document_id)
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDeleteResponse(ok=True)


@router.get("/api/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    project_type: str | None = Query(None),
    document_type: str | None = Query(None),
    document_category: str | None = Query(None),
    specialty: str | None = Query(None),
    volume: str | None = Query(None),
    region: str | None = Query(None),
    project_year: int | None = Query(None),
    owner_type: str | None = Query(None),
    owner_name: str | None = Query(None),
    certificate_type: str | None = Query(None),
    sensitivity: str | None = Query(None),
    usage_scope: str | None = Query(None),
    verified_status: str | None = Query(None),
    tags: list[str] | None = Query(None),
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> KnowledgeSearchResponse:
    try:
        if any(
            [
                project_type,
                document_type,
                document_category,
                specialty,
                volume,
                region,
                project_year,
                owner_type,
                owner_name,
                certificate_type,
                sensitivity,
                usage_scope,
                verified_status,
                tags,
            ]
        ):
            results = retriever.retrieve_filtered(
                query,
                top_k=top_k,
                project_type=project_type,
                document_type=document_type,
                document_category=document_category,
                specialty=specialty,
                volume=volume,
                region=region,
                project_year=project_year,
                owner_type=owner_type,
                owner_name=owner_name,
                certificate_type=certificate_type,
                sensitivity=sensitivity,
                usage_scope=usage_scope,
                verified_status=verified_status,
                tags=tags,
            )
        else:
            results = retriever.retrieve(query, top_k=top_k)
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeSearchResponse(
        query=query,
        results=[
            KnowledgeSearchResult(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                content=result.content,
                metadata=result.metadata,
                score=result.score,
            )
            for result in results
        ],
    )
