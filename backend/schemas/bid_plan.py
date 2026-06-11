from __future__ import annotations

from pydantic import BaseModel, Field


class BidPlanSection(BaseModel):
    title: str
    volume: str = "技术标"
    section_type: str = "content"
    required: bool = True
    requirement_refs: list[str] = Field(default_factory=list)
    evidence_chunk_ids: list[int] = Field(default_factory=list)
    image_document_ids: list[int] = Field(default_factory=list)
    table_required: bool = False
    blank_fields: list[str] = Field(default_factory=list)
    tone_rules: list[str] = Field(default_factory=list)
    forbidden_phrases: list[str] = Field(default_factory=list)


class BidPlan(BaseModel):
    template_name: str = ""
    sections: list[BidPlanSection] = Field(default_factory=list)
    evidence_summary: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def section_for_title(self, title: str) -> BidPlanSection | None:
        normalized = _normalize_title(title)
        for section in self.sections:
            candidate = _normalize_title(section.title)
            if (
                candidate == normalized
                or candidate in normalized
                or normalized in candidate
            ):
                return section
        return None


def _normalize_title(title: str) -> str:
    return (
        title.replace(" ", "")
        .replace("　", "")
        .replace("#", "")
        .replace("、", "")
        .replace("，", "")
        .replace(",", "")
        .strip()
    )
