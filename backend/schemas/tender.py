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
    tenderer_name: str = Field("", description="招标人/采购人名称，未知时为空字符串")
    project_location: str = Field("", description="建设地点/实施地点，未知时为空字符串")
    tender_scope: str = Field("", description="招标范围/工程内容摘要，未知时为空字符串")
    planned_duration: str = Field("", description="计划工期，未知时为空字符串")
    quality_standard: str = Field("", description="质量标准/质量目标，未知时为空字符串")
    safety_target: str = Field("", description="安全目标，未知时为空字符串")
    bid_deadline: str = Field("", description="投标截止时间，未知时为空字符串")
    qualification_list: list[RequirementItem] = Field(default_factory=list)
    technical_score_items: list[RequirementItem] = Field(default_factory=list)
    invalid_bid_items: list[RequirementItem] = Field(default_factory=list)
