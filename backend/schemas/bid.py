from __future__ import annotations

from pydantic import BaseModel, Field


class BidSectionOutline(BaseModel):
    title: str
    required: bool = True
    source_item: str = ""
    focus_points: list[str] = Field(default_factory=list)


class BidGenerationResult(BaseModel):
    outline: list[BidSectionOutline]
    markdown: str
    generated_markdown_path: str
    generated_docx_path: str
    quality_report: dict[str, float | int]
