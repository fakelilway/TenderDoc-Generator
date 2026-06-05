from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowTraceEvent(BaseModel):
    stage: str
    status: str = "running"
    message: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowState(BaseModel):
    project_id: int
    tender_text: str = ""
    parsed: dict[str, Any] | None = None
    retrieved_chunks: dict[str, list[str]] = Field(default_factory=dict)
    draft_markdown: str = ""
    review_report: dict[str, Any] | None = None
    iteration_count: int = 0
    status: str = "created"
    awaiting_human: bool = False
    approved: bool = False
    corrections: dict[str, Any] = Field(default_factory=dict)
    trace_events: list[WorkflowTraceEvent] = Field(default_factory=list)


class WorkflowRunResponse(BaseModel):
    project_id: int
    status: str
    awaiting_human: bool
    iteration_count: int
    review_report: dict[str, Any] | None = None


class ProjectConfirmRequest(BaseModel):
    approved: bool = True
    corrections: dict[str, Any] | None = None


class ProjectConfirmResponse(BaseModel):
    project_id: int
    status: str
    approved: bool
    review_report: dict[str, Any] | None = None
