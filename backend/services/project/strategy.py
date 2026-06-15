"""Pricing strategy, score prediction, response matrix and final checklist."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from agents.pricing_agent import (
    extract_pricing_strategy,
    generate_pricing_strategy_report,
)
from agents.response_matrix_agent import build_response_matrix
from agents.scoring_agent import predict_score
from schemas.tender import TenderRequirements

from . import _runtime
from ._helpers import (
    _fetch_project,
    _project_markdown,
    _project_pricing_strategy,
    _project_requirements,
    _project_review_report,
    _review_report_from_json,
)
from .errors import ProjectNotFoundError


def build_project_pricing_strategy(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    requirements = _project_requirements(project)
    review_report = _project_review_report(project)
    strategy = extract_pricing_strategy(requirements)
    report = generate_pricing_strategy_report(strategy, review_report)

    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET pricing_strategy_json = %s,
                    pricing_strategy_report_json = %s
                WHERE id = %s
                RETURNING id, pricing_strategy_json, pricing_strategy_report_json
                """,
                (Json(strategy.model_dump()), Json(report.model_dump()), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "pricing_strategy": row["pricing_strategy_json"],
        "pricing_report": row["pricing_strategy_report_json"],
    }


def build_project_score_prediction(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    requirements = _project_requirements(project)
    markdown = _project_markdown(project)
    review_report = _project_review_report(project)
    prediction = predict_score(requirements, markdown, review_report)

    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET score_prediction_json = %s
                WHERE id = %s
                RETURNING id, score_prediction_json
                """,
                (Json(prediction.model_dump()), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "score_prediction": row["score_prediction_json"],
    }


def build_project_response_matrix(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    requirements = _project_requirements(project)
    markdown = _project_markdown(project)
    review_report = _project_review_report(project)
    strategy = _project_pricing_strategy(project) or extract_pricing_strategy(
        requirements
    )
    matrix = build_response_matrix(
        project_id,
        requirements,
        markdown,
        review_report=review_report,
        pricing_strategy=strategy,
    )

    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET response_matrix_json = %s
                WHERE id = %s
                RETURNING id, response_matrix_json
                """,
                (Json(matrix.model_dump()), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "response_matrix": row["response_matrix_json"],
    }


def build_final_checklist(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    parsed_json = (
        project.get("confirmed_parsed_json") or project.get("parsed_json") or {}
    )
    review_report = project.get("review_report_json") or {}
    markdown = project.get("edited_markdown") or (
        project.get("workflow_state_json") or {}
    ).get("draft_markdown", "")
    requirements = (
        TenderRequirements.model_validate(parsed_json)
        if parsed_json
        else TenderRequirements()
    )
    pricing_strategy = _project_pricing_strategy(project) or extract_pricing_strategy(
        requirements
    )
    matrix = build_response_matrix(
        project_id,
        requirements,
        markdown,
        review_report=_review_report_from_json(review_report),
        pricing_strategy=pricing_strategy,
    )
    pricing_manual_fields = [
        f"{field.label}：{field.reason}" if field.reason else field.label
        for field in pricing_strategy.manual_fields
        if field.label or field.reason
    ]
    review_points = [
        f"{finding.get('rule', '')}：{finding.get('suggestion') or finding.get('evidence') or '需人工复核'}"
        for finding in review_report.get("findings", [])
        if finding.get("status") != "pass"
    ]
    checklist = {
        "invalid_bid_responses": _checklist_items(
            parsed_json.get("invalid_bid_items", []),
            review_report,
            markdown,
        ),
        "manual_confirmation_points": pricing_manual_fields + review_points,
        "pricing_manual_fields": pricing_manual_fields,
        "attachment_list": _attachment_list(parsed_json),
        "response_matrix": matrix.model_dump(),
    }
    versions = project.get("final_versions_json") or []
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET final_checklist_json = %s,
                    response_matrix_json = %s
                WHERE id = %s
                RETURNING id, final_checklist_json, final_versions_json
                """,
                (Json(checklist), Json(matrix.model_dump()), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "checklist": row["final_checklist_json"] or checklist,
        "versions": row["final_versions_json"] or versions,
    }


def append_final_version(
    project_id: int,
    markdown_path: str | None,
    docx_path: str | None,
) -> list[dict[str, Any]]:
    project = _fetch_project(project_id)
    versions = list(project.get("final_versions_json") or [])
    version_no = len(versions) + 1
    versions.append(
        {
            "version": version_no,
            "markdown_path": markdown_path,
            "docx_path": docx_path,
        }
    )
    with _runtime.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET final_versions_json = %s WHERE id = %s",
                (Json(versions), project_id),
            )
    return versions


def _checklist_items(
    invalid_items: list[dict[str, Any]],
    review_report: dict[str, Any],
    markdown: str,
) -> list[dict[str, Any]]:
    findings = review_report.get("findings", [])
    items = []
    for item in invalid_items:
        snippet = item.get("description", "")[:12]
        items.append(
            {
                "title": item.get("title", "废标风险"),
                "requirement": item.get("description", ""),
                "status": _matching_status(item, findings),
                "responded": bool(snippet and (snippet in markdown)),
                "manual_confirmed": False,
            }
        )
    return items


def _matching_status(item: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    title = item.get("title", "")
    description = item.get("description", "")
    for finding in findings:
        haystack = f"{finding.get('rule', '')} {finding.get('evidence', '')}"
        if title and title in haystack:
            return finding.get("status", "warning")
        if description[:12] and description[:12] in haystack:
            return finding.get("status", "warning")
    return "pending"


def _attachment_list(parsed_json: dict[str, Any]) -> list[str]:
    titles = [
        item.get("title", "") for item in parsed_json.get("qualification_list", [])
    ]
    defaults = ["营业执照", "资质证书", "安全生产许可证", "项目经理证书", "业绩证明"]
    return [title for title in titles if title] or defaults
