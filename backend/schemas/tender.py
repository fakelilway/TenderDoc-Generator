from __future__ import annotations

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    source_text: str = Field("", description="原文片段，用于人工核对")
    page_number: int | None = Field(None, description="来源页码，未知时为空")


class RequirementItem(BaseModel):
    title: str = Field(..., description="要求或条款的简短标题")
    description: str = Field(..., description="从招标文件抽取的具体要求")
    source: SourceReference = Field(default_factory=SourceReference)


class TenderRequirements(BaseModel):
    project_name: str = Field("", description="项目名称，未知时为空字符串")
    qualification_list: list[RequirementItem] = Field(default_factory=list)
    technical_score_items: list[RequirementItem] = Field(default_factory=list)
    invalid_bid_items: list[RequirementItem] = Field(default_factory=list)
