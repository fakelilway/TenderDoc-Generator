from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile

from rag import retriever
from schemas.knowledge import (
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeUploadResponse,
)
from schemas.project import (
    ProjectCreateResponse,
    ProjectResultResponse,
    ProjectReviewResponse,
    ProjectStatusResponse,
)
from services import knowledge_service, project_service
from services.project_service import ProjectNotFoundError


app = FastAPI(title="TenderDoc Generator API")


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, ProjectNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/knowledge/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge(
    file: UploadFile = File(...),
) -> KnowledgeUploadResponse:
    try:
        indexed = knowledge_service.index_uploaded_knowledge(
            file_bytes=await file.read(),
            filename=file.filename or "knowledge.txt",
            content_type=file.content_type,
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeUploadResponse(**indexed)


@app.get("/api/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
) -> KnowledgeSearchResponse:
    try:
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


@app.post("/api/project/create", response_model=ProjectCreateResponse)
async def create_project(
    name: str = Form(...),
    tender_file: UploadFile = File(...),
) -> ProjectCreateResponse:
    try:
        project = project_service.create_project(
            name=name,
            file_bytes=await tender_file.read(),
            filename=tender_file.filename or "tender.txt",
            content_type=tender_file.content_type,
        )
    except Exception as error:
        _raise_http_error(error)

    return ProjectCreateResponse(
        project_id=project["id"],
        status=project["status"],
        tender_file_path=project["tender_file_path"],
    )


@app.get("/api/project/{project_id}/status", response_model=ProjectStatusResponse)
def project_status(project_id: int) -> ProjectStatusResponse:
    try:
        return ProjectStatusResponse(**project_service.get_project_status(project_id))
    except Exception as error:
        _raise_http_error(error)


@app.post("/api/project/{project_id}/parse", response_model=ProjectResultResponse)
def parse_project(project_id: int) -> ProjectResultResponse:
    try:
        project = project_service.parse_project(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectResultResponse(
        project_id=project["id"],
        status=project["status"],
        parsed_json=project["parsed_json"],
    )


@app.post("/api/project/{project_id}/generate", response_model=ProjectResultResponse)
def generate_project(project_id: int) -> ProjectResultResponse:
    return parse_project(project_id)


@app.get("/api/project/{project_id}/result", response_model=ProjectResultResponse)
def project_result(project_id: int) -> ProjectResultResponse:
    try:
        return ProjectResultResponse(**project_service.get_project_result(project_id))
    except Exception as error:
        _raise_http_error(error)


@app.get("/api/project/{project_id}/review", response_model=ProjectReviewResponse)
def project_review(project_id: int) -> ProjectReviewResponse:
    try:
        return ProjectReviewResponse(**project_service.get_project_review(project_id))
    except Exception as error:
        _raise_http_error(error)
