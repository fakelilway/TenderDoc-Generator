from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ReviewStatus = Literal["pass", "fail", "warning"]


class ReviewLocation(BaseModel):
    line_number: int | None = None
    paragraph_index: int | None = None
    snippet: str = ""


class ReviewFinding(BaseModel):
    rule: str
    field: str = ""
    status: ReviewStatus
    severity: str = "medium"
    suggestion: str = ""
    evidence: str = ""
    location: ReviewLocation = Field(default_factory=ReviewLocation)


class ReviewReport(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    warning_count: int = 0
    has_failures: bool = False


class InvalidBidRule(BaseModel):
    id: str
    field: str
    keyword_patterns: list[str]
    required_value: str
    severity: str = "medium"
    suggestion: str = ""
