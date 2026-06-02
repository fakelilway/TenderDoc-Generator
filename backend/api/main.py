from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from schemas.project import (
    ProjectCreateResponse,
    ProjectResultResponse,
    ProjectReviewResponse,
    ProjectStatusResponse,
)
from services import project_service
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
