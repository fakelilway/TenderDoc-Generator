from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BidTemplateSection(BaseModel):
    title: str
    start_page: int | None = None
    end_page: int | None = None
    level: int = 1
    section_type: str = "content"
    source_page_label: str = ""
    sample_snippet: str = ""
    children: list["BidTemplateSection"] = Field(default_factory=list)


class BidTemplate(BaseModel):
    template_name: str
    source_file: str
    page_count: int
    project_name: str = ""
    company_name: str = ""
    envelope_type: str = ""
    document_type: str = ""
    main_sections: list[BidTemplateSection] = Field(default_factory=list)
    construction_design_sections: list[BidTemplateSection] = Field(default_factory=list)
    appendix_sections: list[BidTemplateSection] = Field(default_factory=list)
    fixed_form_sections: list[BidTemplateSection] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    notes: list[str] = Field(default_factory=list)
