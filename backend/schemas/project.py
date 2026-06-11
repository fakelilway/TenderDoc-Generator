from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProjectCreateResponse(BaseModel):
    project_id: int
    status: str
    tender_file_path: str | None = None


class ProjectSummary(BaseModel):
    project_id: int
    name: str
    status: str
    created_at: datetime | None = None
    owner_user_id: int | None = None
    owner_username: str | None = None
    owner_display_name: str | None = None
    has_download: bool = False


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary] = []


class ProjectDeleteResponse(BaseModel):
    ok: bool = True


class ProjectTemplateRequest(BaseModel):
    template_id: int | None = None


class ProjectTemplateResponse(BaseModel):
    project_id: int
    template_id: int | None = None


class ProjectStatusResponse(BaseModel):
    project_id: int
    status: str
    parsed: bool


class ProjectResultResponse(BaseModel):
    project_id: int
    status: str
    parsed_json: dict[str, Any] | None = None


class ProjectDownloadResponse(BaseModel):
    project_id: int
    status: str
    download_url: str
    expires_in: int = 3600
    artifact: str = "docx"
    artifact_label: str | None = None
    filename: str | None = None


class DeliveryVolumePreview(BaseModel):
    key: str
    label: str
    markdown: str
    line_count: int = 0
    char_count: int = 0


class ProjectDeliveryPreviewResponse(BaseModel):
    project_id: int
    status: str
    volumes: dict[str, DeliveryVolumePreview]
