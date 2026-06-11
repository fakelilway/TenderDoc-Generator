from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TemplateVolumeProfile(BaseModel):
    name: str
    role: str = "content"
    section_titles: list[str] = Field(default_factory=list)


class TemplateSlot(BaseModel):
    section_title: str
    slot_type: str
    description: str
    required: bool = True
    evidence_categories: list[str] = Field(default_factory=list)


class TemplateProfile(BaseModel):
    template_name: str
    source_file: str = ""
    project_type: str | None = None
    specialty: str | None = None
    envelope_type: str = ""
    document_type: str = ""
    volumes: list[TemplateVolumeProfile] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)
    fixed_forms: list[str] = Field(default_factory=list)
    appendix_tables: list[str] = Field(default_factory=list)
    image_slots: list[TemplateSlot] = Field(default_factory=list)
    table_slots: list[TemplateSlot] = Field(default_factory=list)
    blank_fields: list[str] = Field(default_factory=list)
    tone_rules: list[str] = Field(default_factory=list)
    forbidden_phrases: list[str] = Field(default_factory=list)
    generated_by: str = "deterministic_template_profile_agent"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    notes: list[str] = Field(default_factory=list)
