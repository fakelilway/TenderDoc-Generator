"""Shared, mostly-pure helpers used across the project service submodules.

Functions here either have no side effects or fetch project rows via the
facade-patchable ``_connect`` (resolved through :mod:`._runtime`). They are
deliberately free of business-grouping so every submodule can depend on them
without creating import cycles between the grouped submodules.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

from schemas.review import ReviewReport
from schemas.strategy import PricingStrategy
from schemas.tender import TenderRequirements
from schemas.workflow import WorkflowState, WorkflowTraceEvent

from . import _runtime
from .errors import ProjectNotFoundError

_RUNNING_STATUSES = {"uploading", "parsing", "processing", "generating", "reviewing"}
_STATUS_ORDER = {
    "idle": 0,
    "uploading": 1,
    "uploaded": 2,
    "parsing": 3,
    "parsed": 4,
    "parsed_confirmed": 5,
    "outline_ready": 6,
    "outline_review": 6,
    "outline_confirmed": 7,
    "processing": 8,
    "generating": 9,
    "reviewing": 10,
    "human_review": 11,
    "needs_revision": 11,
    "draft_saved": 12,
    "generated": 13,
    "approved": 14,
    "finished": 15,
    "generation_failed": 98,
    "failed": 99,
}


def _safe_filename(filename: str) -> str:
    basename = Path(filename or "tender.txt").name
    cleaned = re.sub(r"[^\w.\-一-鿿]+", "_", basename, flags=re.UNICODE)
    return cleaned.strip("._") or "tender.txt"


def _status_rank(status: str | None) -> int:
    if not status:
        return -1
    return _STATUS_ORDER.get(status, -1)


def _resolve_project_status(project_status: str, workflow_status: str | None) -> str:
    """Prefer the newest known status without letting stale workflow JSON rewind UI."""
    if project_status in _RUNNING_STATUSES:
        return project_status
    if workflow_status and _status_rank(workflow_status) > _status_rank(project_status):
        return workflow_status
    return project_status


def _workflow_patch(project_id: int, status: str, **fields: Any) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "status": status,
        **fields,
    }


def _hydrated_workflow_state(project: dict[str, Any]) -> dict[str, Any] | None:
    workflow_state = dict(project.get("workflow_state_json") or {})
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    has_saved_workflow_context = any(
        (
            parsed_json,
            project.get("bid_outline_json"),
            project.get("document_outline_json"),
            project.get("selected_chunk_ids"),
        )
    )
    if not workflow_state and not has_saved_workflow_context:
        return None

    status = _resolve_project_status(project["status"], workflow_state.get("status"))
    workflow_state["project_id"] = project["id"]
    workflow_state["status"] = status
    if parsed_json:
        workflow_state["parsed"] = parsed_json
    if project.get("bid_outline_json") is not None:
        workflow_state["bid_outline"] = project.get("bid_outline_json") or []
    if project.get("document_outline_json") is not None:
        workflow_state["document_outline"] = project.get("document_outline_json") or []
    if project.get("selected_chunk_ids") is not None:
        workflow_state["selected_chunk_ids"] = project.get("selected_chunk_ids") or []
    return workflow_state


def _fetch_project(project_id: int) -> dict[str, Any]:
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    tender_file_path,
                    tender_text,
                    parsed_json,
                    generated_markdown_path,
                    generated_docx_path,
                    generation_quality_json,
                    review_report_json,
                    workflow_state_json,
                    confirmed_parsed_json,
                    bid_outline_json,
                    document_outline_json,
                    selected_chunk_ids,
                    selected_personnel,
                    edited_markdown,
                    final_checklist_json,
                    final_versions_json,
                    pricing_strategy_json,
                    pricing_strategy_report_json,
                    score_prediction_json,
                    response_matrix_json,
                    status,
                    template_id,
                    created_at
                FROM projects
                WHERE id = %s
                """,
                (project_id,),
            )
            row = cursor.fetchone()

    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")

    return dict(row)


def _fetch_project_status(project_id: int) -> dict[str, Any]:
    """Fetch only the lightweight columns needed for status polling.

    Avoids selecting the JSONB blobs that ``_fetch_project`` pulls; the 2s
    frontend poll only needs scalar fields plus derived flags.
    """
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    status,
                    owner_user_id,
                    created_at,
                    parsed_json IS NOT NULL AS parsed,
                    workflow_state_json->>'status' AS workflow_status
                FROM projects
                WHERE id = %s
                """,
                (project_id,),
            )
            row = cursor.fetchone()

    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")

    return dict(row)


def _project_summary(row: dict[str, Any]) -> dict[str, Any]:
    workflow_state = row.get("workflow_state_json") or {}
    project_status = row["status"]
    status = _resolve_project_status(project_status, workflow_state.get("status"))
    return {
        "project_id": int(row["id"]),
        "name": row["name"],
        "status": status,
        "created_at": row["created_at"],
        "owner_user_id": row.get("owner_user_id"),
        "owner_username": row.get("owner_username"),
        "owner_display_name": row.get("owner_display_name"),
        "has_download": bool(row.get("generated_docx_path")),
    }


def _parse_workflow_state(
    project_id: int,
    status: str,
    trace_status: str,
    message: str,
    parsed_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return WorkflowState(
        project_id=project_id,
        status=status,
        parsed=parsed_json,
        trace_events=[
            WorkflowTraceEvent(stage="parse", status=trace_status, message=message)
        ],
    ).model_dump(mode="json")


def _project_requirements(project: dict[str, Any]) -> TenderRequirements:
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    if not parsed_json:
        raise ValueError("Project has no parsed requirements")
    return TenderRequirements.model_validate(parsed_json)


def _project_markdown(project: dict[str, Any]) -> str:
    markdown = project.get("edited_markdown") or (
        project.get("workflow_state_json") or {}
    ).get("draft_markdown", "")
    if not markdown:
        raise ValueError("Project has no draft markdown")
    return markdown


def _review_report_from_json(payload: dict[str, Any] | None) -> ReviewReport | None:
    if not payload:
        return None
    return ReviewReport.model_validate(payload)


def _project_review_report(project: dict[str, Any]) -> ReviewReport | None:
    return _review_report_from_json(project.get("review_report_json"))


def _project_pricing_strategy(project: dict[str, Any]) -> PricingStrategy | None:
    payload = project.get("pricing_strategy_json")
    if not payload:
        return None
    return PricingStrategy.model_validate(payload)
