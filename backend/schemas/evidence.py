from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    chunk_id: int | None = None
    document_id: int | None = None
    title: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_type: str = "reference"
    document_category: str | None = None
    certificate_type: str | None = None
    owner_type: str | None = None
    owner_name: str | None = None
    score: float | None = None

    def search_text(self) -> str:
        tags = self.metadata.get("tags") or []
        tag_text = " ".join(str(tag) for tag in tags if str(tag).strip())
        values = [
            self.title,
            self.content,
            self.evidence_type,
            self.document_category,
            self.certificate_type,
            self.owner_type,
            self.owner_name,
            tag_text,
        ]
        for key in (
            "file_name",
            "document_type",
            "project_type",
            "specialty",
            "volume",
            "region",
            "project_year",
            "usage_scope",
            "verified_status",
        ):
            value = self.metadata.get(key)
            if value:
                values.append(str(value))
        return " ".join(str(value) for value in values if value)


class EvidencePack(BaseModel):
    company_certificates: list[EvidenceItem] = Field(default_factory=list)
    person_certificates: list[EvidenceItem] = Field(default_factory=list)
    performance_projects: list[EvidenceItem] = Field(default_factory=list)
    technical_schemes: list[EvidenceItem] = Field(default_factory=list)
    image_evidence: list[EvidenceItem] = Field(default_factory=list)
    pricing_attachments: list[EvidenceItem] = Field(default_factory=list)
    table_attachments: list[EvidenceItem] = Field(default_factory=list)
    other_references: list[EvidenceItem] = Field(default_factory=list)
    selected_chunk_ids: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def all_text_items(self) -> list[EvidenceItem]:
        return [
            *self.company_certificates,
            *self.person_certificates,
            *self.performance_projects,
            *self.technical_schemes,
            *self.pricing_attachments,
            *self.table_attachments,
            *self.other_references,
        ]

    def all_items(self) -> list[EvidenceItem]:
        return [*self.all_text_items(), *self.image_evidence]

    def counts(self) -> dict[str, int]:
        return {
            "company_certificates": len(self.company_certificates),
            "person_certificates": len(self.person_certificates),
            "performance_projects": len(self.performance_projects),
            "technical_schemes": len(self.technical_schemes),
            "image_evidence": len(self.image_evidence),
            "pricing_attachments": len(self.pricing_attachments),
            "table_attachments": len(self.table_attachments),
            "other_references": len(self.other_references),
            "selected_chunk_ids": len(self.selected_chunk_ids),
        }
