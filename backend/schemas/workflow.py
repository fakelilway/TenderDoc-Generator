from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowTraceEvent(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    stage: str
    status: str = "running"
    message: str
    duration_ms: int | None = None
    model_name: str | None = None
    fallback: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowState(BaseModel):
    project_id: int
    tender_text: str = ""
    parsed: dict[str, Any] | None = None
    bid_outline: list[dict[str, Any]] = Field(default_factory=list)
    selected_chunk_ids: list[int] = Field(default_factory=list)
    rag_references: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_chunks: dict[str, list[str]] = Field(default_factory=dict)
    draft_markdown: str = ""
    final_checklist: dict[str, Any] | None = None
    final_versions: list[dict[str, Any]] = Field(default_factory=list)
    review_report: dict[str, Any] | None = None
    pricing_strategy: dict[str, Any] | None = None
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


class ParsedConfirmationRequest(BaseModel):
    parsed_json: dict[str, Any]


class ParsedConfirmationResponse(BaseModel):
    project_id: int
    status: str
    confirmed_parsed_json: dict[str, Any]


class BidOutlineRequest(BaseModel):
    outline: list[dict[str, Any]]


class BidOutlineResponse(BaseModel):
    project_id: int
    status: str
    bid_outline: list[dict[str, Any]]


class KnowledgeSelectionRequest(BaseModel):
    selected_chunk_ids: list[int] = Field(default_factory=list)


class KnowledgeSelectionResponse(BaseModel):
    project_id: int
    selected_chunk_ids: list[int]
    references: list[dict[str, Any]] = Field(default_factory=list)


class DraftMarkdownRequest(BaseModel):
    markdown: str


class DraftMarkdownResponse(BaseModel):
    project_id: int
    status: str
    draft_markdown: str
    review_report: dict[str, Any] | None = None


class FinalChecklistResponse(BaseModel):
    project_id: int
    checklist: dict[str, Any]
    versions: list[dict[str, Any]] = Field(default_factory=list)
