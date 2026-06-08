from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.review import ReviewLocation


class PricingManualField(BaseModel):
    label: str
    reason: str
    source_text: str = ""
    required: bool = True


class PricingCondition(BaseModel):
    name: str
    value: str = ""
    risk_level: str = "medium"
    source_text: str = ""
    manual_verify: bool = False


class PricingStrategy(BaseModel):
    project_name: str = ""
    project_scale: str = "人工确认"
    schedule_risk: str = "medium"
    payment_terms: list[PricingCondition] = Field(default_factory=list)
    competition_intensity: str = "medium"
    quote_risk: str = "medium"
    guarantee_requirements: list[PricingCondition] = Field(default_factory=list)
    manual_fields: list[PricingManualField] = Field(default_factory=list)
    extracted_conditions: list[PricingCondition] = Field(default_factory=list)


class PricingStrategyReport(BaseModel):
    project_name: str = ""
    strategy_suggestions: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    commercial_response_notes: list[str] = Field(default_factory=list)
    manual_confirmation_points: list[str] = Field(default_factory=list)
    prohibited_auto_pricing: bool = True


class ProjectPricingStrategyResponse(BaseModel):
    project_id: int
    pricing_strategy: PricingStrategy
    pricing_report: PricingStrategyReport


class ScoreItemPrediction(BaseModel):
    title: str
    max_score: float = 0
    predicted_score: float = 0
    coverage_status: str = "warning"
    rationale: str = ""
    improvement_suggestion: str = ""
    location: ReviewLocation = Field(default_factory=ReviewLocation)


class ScorePrediction(BaseModel):
    project_name: str = ""
    total_max_score: float = 0
    predicted_total_score: float = 0
    score_rate: float = 0
    win_probability: float | None = None
    win_probability_rationale: str = ""
    uncertainty_notes: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    items: list[ScoreItemPrediction] = Field(default_factory=list)


class ProjectScorePredictionResponse(BaseModel):
    project_id: int
    score_prediction: ScorePrediction


class ResponseMatrixRow(BaseModel):
    requirement_type: str
    requirement_title: str
    requirement_text: str
    response_status: str = "warning"
    response_location: ReviewLocation = Field(default_factory=ReviewLocation)
    response_section: str = ""
    review_status: str = "warning"
    manual_confirmation_required: bool = False
    manual_confirmation_note: str = ""


class ResponseMatrix(BaseModel):
    project_id: int
    rows: list[ResponseMatrixRow] = Field(default_factory=list)
    invalid_bid_coverage_count: int = 0
    total_invalid_bid_count: int = 0


class ProjectResponseMatrixResponse(BaseModel):
    project_id: int
    response_matrix: ResponseMatrix
