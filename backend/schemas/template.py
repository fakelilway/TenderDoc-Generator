from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TemplateSummary(BaseModel):
    id: int
    name: str
    source_filename: str | None = None
    project_type: str | None = None
    specialty: str | None = None
    envelope_type: str | None = None
    region: str | None = None
    project_year: int | None = None
    tags: list[str] = []
    project_name: str | None = None
    page_count: int | None = None
    created_by: int | None = None
    created_at: datetime | None = None


class TemplateListResponse(BaseModel):
    templates: list[TemplateSummary] = []


class TemplateUploadResponse(BaseModel):
    template: TemplateSummary


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    project_type: str | None = None
    specialty: str | None = None
    envelope_type: str | None = None
    region: str | None = None
    project_year: int | None = None
    tags: list[str] | None = None


class TemplateRecommendation(BaseModel):
    template: TemplateSummary
    match_score: float
    match_reasons: list[str] = []


class TemplateRecommendResponse(BaseModel):
    recommendations: list[TemplateRecommendation] = []


class TemplateDeleteResponse(BaseModel):
    ok: bool = True
