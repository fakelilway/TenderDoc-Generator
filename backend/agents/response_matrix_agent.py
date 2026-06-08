from __future__ import annotations

import re

from agents.reviewer_agent import find_markdown_location
from schemas.review import ReviewFinding, ReviewReport, ReviewStatus
from schemas.strategy import PricingStrategy, ResponseMatrix, ResponseMatrixRow
from schemas.tender import RequirementItem, TenderRequirements


def build_response_matrix(
    project_id: int,
    requirements: TenderRequirements,
    markdown: str,
    review_report: ReviewReport | None = None,
    pricing_strategy: PricingStrategy | None = None,
) -> ResponseMatrix:
    rows: list[ResponseMatrixRow] = []
    rows.extend(
        _rows_for_items(
            requirement_type="qualification",
            items=requirements.qualification_list,
            markdown=markdown,
            review_report=review_report,
            manual_confirmation_required=True,
        )
    )
    invalid_rows = _rows_for_items(
        requirement_type="invalid_bid_item",
        items=requirements.invalid_bid_items,
        markdown=markdown,
        review_report=review_report,
        manual_confirmation_required=True,
    )
    rows.extend(invalid_rows)
    rows.extend(
        _rows_for_items(
            requirement_type="technical_score_item",
            items=requirements.technical_score_items,
            markdown=markdown,
            review_report=review_report,
            manual_confirmation_required=False,
        )
    )
    if pricing_strategy:
        rows.extend(_pricing_rows(pricing_strategy, markdown))

    return ResponseMatrix(
        project_id=project_id,
        rows=rows,
        invalid_bid_coverage_count=sum(
            1 for row in invalid_rows if row.review_status == "pass"
        ),
        total_invalid_bid_count=len(requirements.invalid_bid_items),
    )


def _rows_for_items(
    requirement_type: str,
    items: list[RequirementItem],
    markdown: str,
    review_report: ReviewReport | None,
    manual_confirmation_required: bool,
) -> list[ResponseMatrixRow]:
    rows: list[ResponseMatrixRow] = []
    for index, item in enumerate(items):
        keywords = _keywords(f"{item.title} {item.description}")
        location = find_markdown_location(markdown, keywords)
        response_found = any(
            re.search(keyword, markdown, flags=re.IGNORECASE)
            for keyword in keywords
        )
        finding = _matching_finding(requirement_type, index, item, review_report)
        review_status: ReviewStatus | str
        if finding:
            review_status = finding.status
        else:
            review_status = "pass" if response_found else "warning"
        rows.append(
            ResponseMatrixRow(
                requirement_type=requirement_type,
                requirement_title=item.title,
                requirement_text=item.description,
                response_status="found" if response_found else "missing",
                response_location=location,
                response_section=_section_for_line(markdown, location.line_number),
                review_status=review_status,
                manual_confirmation_required=manual_confirmation_required,
                manual_confirmation_note=(
                    "需人工核对原文、附件、证书或承诺一致性。"
                    if manual_confirmation_required
                    else ""
                ),
            )
        )
    return rows


def _pricing_rows(
    strategy: PricingStrategy,
    markdown: str,
) -> list[ResponseMatrixRow]:
    rows: list[ResponseMatrixRow] = []
    for field in strategy.manual_fields:
        keywords = _keywords(field.label)
        location = find_markdown_location(markdown, keywords)
        response_found = any(
            re.search(keyword, markdown, flags=re.IGNORECASE)
            for keyword in keywords
        )
        rows.append(
            ResponseMatrixRow(
                requirement_type="commercial_manual_field",
                requirement_title=field.label,
                requirement_text=field.reason,
                response_status="found" if response_found else "missing",
                response_location=location,
                response_section=_section_for_line(markdown, location.line_number),
                review_status="warning",
                manual_confirmation_required=True,
                manual_confirmation_note="商务报价字段必须人工填写或复核，系统不得自动定价。",
            )
        )
    return rows


def _matching_finding(
    requirement_type: str,
    index: int,
    item: RequirementItem,
    review_report: ReviewReport | None,
) -> ReviewFinding | None:
    if not review_report:
        return None
    if requirement_type == "invalid_bid_item":
        rule_id = f"invalid_bid_item_{index + 1}"
        for finding in review_report.findings:
            if finding.rule == rule_id:
                return finding
    text = f"{item.title} {item.description}"
    for finding in review_report.findings:
        haystack = f"{finding.rule} {finding.field} {finding.evidence} {finding.suggestion}"
        if item.title and item.title in haystack:
            return finding
        if any(keyword in haystack for keyword in _keywords(text)[:3]):
            return finding
    return None


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text)
    filtered = [
        token
        for token in tokens
        if token not in {"要求", "投标", "评分", "人工", "确认", "待补充"}
    ]
    return filtered[:6] or [text[:20]]


def _section_for_line(markdown: str, line_number: int | None) -> str:
    if not line_number:
        return ""
    section = ""
    for current, line in enumerate(markdown.splitlines(), start=1):
        if current > line_number:
            break
        if line.lstrip().startswith("#"):
            section = line.strip("# ").strip()
    return section
