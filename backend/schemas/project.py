from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ProjectCreateResponse(BaseModel):
    project_id: int
    status: str
    tender_file_path: str | None = None


class ProjectStatusResponse(BaseModel):
    project_id: int
    status: str
    parsed: bool


class ProjectResultResponse(BaseModel):
    project_id: int
    status: str
    parsed_json: dict[str, Any] | None = None


class ProjectReviewResponse(BaseModel):
    project_id: int
    status: str
    invalid_bid_items: list[dict[str, Any]]


class ProjectGenerateResponse(BaseModel):
    project_id: int
    status: str
    generated_markdown_path: str
    generated_docx_path: str
    quality_report: dict[str, Any]
