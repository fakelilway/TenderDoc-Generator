from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import (
    build_bid_document_outline,
    build_bid_outline,
    load_bid_template,
)
from schemas.bid import BidDocumentOutlineSection
from agents.parser_agent import parse_tender
from agents.pricing_agent import (
    extract_pricing_strategy,
    generate_pricing_strategy_report,
)
from agents.response_matrix_agent import build_response_matrix
from agents.reviewer_agent import review
from agents.scoring_agent import predict_score
from core.config import settings
from core.db import get_db_connection
from schemas.review import ReviewReport
from schemas.strategy import PricingStrategy
from schemas.tender import TenderRequirements
from utils.docx_exporter import (
    build_export_filename,
    markdown_to_docx,
    markdown_to_pdf,
    split_delivery_markdown,
)
from utils.file_parser import extract_text
from utils.minio_client import minio_client


class ProjectNotFoundError(Exception):
    """Raised when a project id is not present in the database."""


class ProjectAccessError(Exception):
    """Raised when a user tries to access a project they do not own."""


_RUNNING_STATUSES = {"uploading", "parsing", "processing", "generating", "reviewing"}


@contextmanager
def _connect() -> Iterator[psycopg2.extensions.connection]:
    """Yield a pooled connection that commits on success, rolls back on error.

    Wraps ``core.db.get_db_connection`` so every ``with _connect() as conn:``
    call site keeps the transactional semantics it had with a raw psycopg2
    connection used as a context manager, while reusing pooled connections.
    """
    with get_db_connection() as conn:
        with conn:
            yield conn


def _safe_filename(filename: str) -> str:
    basename = Path(filename or "tender.txt").name
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", basename, flags=re.UNICODE)
    return cleaned.strip("._") or "tender.txt"


def _tender_object_name(project_id: int, filename: str) -> str:
    return f"projects/{project_id}/tender/{uuid4().hex}_{_safe_filename(filename)}"


def _fetch_project(project_id: int) -> dict[str, Any]:
    with _connect() as conn:
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
    with _connect() as conn:
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


def create_project(
    name: str,
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
    owner_user_id: int | None = None,
    template_id: int | None = None,
) -> dict[str, Any]:
    """Create a project, upload the tender file, and store its object path."""
    if not file_bytes:
        raise ValueError("Uploaded tender file is empty")

    safe_name = name.strip()
    if not safe_name:
        raise ValueError("Project name is required")

    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO projects (name, status, owner_user_id, template_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, tender_file_path, parsed_json, status, created_at
                """,
                (safe_name, "uploading", owner_user_id, template_id),
            )
            project = dict(cursor.fetchone())

            object_name = _tender_object_name(project["id"], filename)
            minio_client.upload_file(settings.minio_bucket, file_bytes, object_name)

            cursor.execute(
                """
                INSERT INTO documents (project_id, file_name, file_path, file_type)
                VALUES (%s, %s, %s, %s)
                """,
                (project["id"], _safe_filename(filename), object_name, content_type),
            )
            cursor.execute(
                """
                UPDATE projects
                SET tender_file_path = %s, status = %s
                WHERE id = %s
                RETURNING id, name, tender_file_path, parsed_json, status, created_at
                """,
                (object_name, "uploaded", project["id"]),
            )
            return dict(cursor.fetchone())


def get_project(project_id: int) -> dict[str, Any]:
    return _fetch_project(project_id)


def get_project_owner(project_id: int) -> int | None:
    """Return the owner user id for a project, or None when unowned."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT owner_user_id FROM projects WHERE id = %s",
                (project_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return row["owner_user_id"]


def authorize_project_access(
    project_id: int,
    user_id: int,
    is_admin: bool = False,
) -> int | None:
    """Ensure ``user_id`` may access ``project_id``.

    Admins may access any project, including legacy projects with no owner
    recorded. Regular users may only access projects they own. Raises
    ``ProjectAccessError`` otherwise and ``ProjectNotFoundError`` when the
    project does not exist.
    """
    owner_id = get_project_owner(project_id)
    if is_admin:
        return owner_id
    if owner_id is None or owner_id != user_id:
        raise ProjectAccessError("无权访问该项目")
    return owner_id


def delete_project(project_id: int) -> None:
    """Delete a project and its stored artifacts.

    Document/knowledge rows cascade via the ``projects`` foreign key. MinIO
    objects are removed on a best-effort basis so a missing object never blocks
    deletion of the database row.
    """
    project = _fetch_project(project_id)
    for object_key in (
        project.get("tender_file_path"),
        project.get("generated_markdown_path"),
        project.get("generated_docx_path"),
    ):
        if object_key:
            try:
                minio_client.remove_file(settings.minio_bucket, object_key)
            except Exception:
                pass

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    invalidate_delivery_preview_cache(project_id)


def _project_summary(row: dict[str, Any]) -> dict[str, Any]:
    workflow_state = row.get("workflow_state_json") or {}
    project_status = row["status"]
    status = (
        project_status
        if project_status in _RUNNING_STATUSES
        else workflow_state.get("status") or project_status
    )
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


def list_projects(
    viewer_id: int,
    is_admin: bool = False,
    owner_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List projects visible to the requesting user, newest first.

    Regular users only see projects they own; legacy ownerless projects are
    admin-only. Admins see every project, optionally filtered to one owner.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if is_admin:
        if owner_user_id is not None:
            clauses.append("p.owner_user_id = %s")
            params.append(owner_user_id)
    else:
        clauses.append("p.owner_user_id = %s")
        params.append(viewer_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""
                SELECT
                    p.id,
                    p.name,
                    p.status,
                    p.created_at,
                    p.owner_user_id,
                    p.generated_docx_path,
                    p.workflow_state_json,
                    u.username AS owner_username,
                    u.display_name AS owner_display_name
                FROM projects p
                LEFT JOIN users u ON u.id = p.owner_user_id
                {where}
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
    return [_project_summary(dict(row)) for row in rows]


def get_project_status(project_id: int) -> dict[str, Any]:
    project = _fetch_project_status(project_id)
    project_status = project["status"]
    return {
        "project_id": project["id"],
        "status": (
            project_status
            if project_status in _RUNNING_STATUSES
            else project["workflow_status"] or project_status
        ),
        "parsed": bool(project["parsed"]),
    }


def parse_project(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    if not project["tender_file_path"]:
        raise ValueError("Project has no tender file path")
    if project.get("parsed_json"):
        return project

    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT file_name, file_path, file_type
                FROM documents
                WHERE project_id = %s AND file_path = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id, project["tender_file_path"]),
            )
            document = cursor.fetchone()

            if not document:
                raise ValueError("Project tender document record was not found")

            cursor.execute(
                "UPDATE projects SET status = %s WHERE id = %s",
                ("parsing", project_id),
            )

    try:
        file_bytes = minio_client.download_bytes(
            settings.minio_bucket,
            str(document["file_path"]),
        )
        text = extract_text(
            file_bytes,
            filename=str(document["file_name"]),
            content_type=document["file_type"],
        )
        parsed = parse_tender(text)
        parsed_json = parsed.model_dump()
        status = "parsed"
    except Exception:
        with _connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE projects SET status = %s WHERE id = %s",
                    ("failed", project_id),
                )
        raise

    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET parsed_json = %s,
                    tender_text = %s,
                    status = %s
                WHERE id = %s
                RETURNING id, name, tender_file_path, parsed_json, status, created_at
                """,
                (Json(parsed_json), text, status, project_id),
            )
            return dict(cursor.fetchone())


def get_project_result(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    return {
        "project_id": project["id"],
        "status": project["status"],
        "parsed_json": project.get("confirmed_parsed_json") or project["parsed_json"],
    }


def confirm_parsed_result(
    project_id: int, parsed_json: dict[str, Any]
) -> dict[str, Any]:
    confirmed = TenderRequirements.model_validate(parsed_json).model_dump()
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET confirmed_parsed_json = %s,
                    parsed_json = %s,
                    status = %s
                WHERE id = %s
                RETURNING id, status, confirmed_parsed_json
                """,
                (Json(confirmed), Json(confirmed), "parsed_confirmed", project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return dict(row)


def build_project_outline(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    if not parsed_json:
        raise ValueError("Project has no parsed requirements")
    requirements = TenderRequirements.model_validate(parsed_json)
    from services import template_service

    bid_template = (
        template_service.bid_template_for_project(project_id) or load_bid_template()
    )
    outline = [
        section.model_dump()
        for section in build_bid_outline(requirements, bid_template)
    ]
    document_outline = [
        section.model_dump()
        for section in build_bid_document_outline(requirements, bid_template)
    ]
    return save_project_outline(
        project_id,
        outline,
        document_outline=document_outline,
        status="outline_ready",
    )


def save_project_outline(
    project_id: int,
    outline: list[dict[str, Any]],
    document_outline: list[dict[str, Any]] | None = None,
    status: str = "outline_confirmed",
) -> dict[str, Any]:
    if not outline:
        raise ValueError("Bid outline cannot be empty")
    clean_outline = []
    for item in outline:
        title = str(item.get("title", "")).strip()
        if not title:
            raise ValueError("Each outline section requires a title")
        clean_outline.append(
            {
                "title": title,
                "required": bool(item.get("required", True)),
                "source_item": str(item.get("source_item") or ""),
                "focus_points": [
                    str(point)
                    for point in item.get("focus_points", [])
                    if str(point).strip()
                ],
            }
        )
    clean_document_outline = (
        _clean_document_outline(document_outline)
        if document_outline
        else _build_document_outline_for_saved_technical_outline(
            project_id, clean_outline
        )
    )
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET bid_outline_json = %s,
                    document_outline_json = %s,
                    status = %s
                WHERE id = %s
                RETURNING id, status, bid_outline_json, document_outline_json
                """,
                (Json(clean_outline), Json(clean_document_outline), status, project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return dict(row)


def _clean_document_outline(outline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        BidDocumentOutlineSection.model_validate(item).model_dump()
        for item in outline
        if str(item.get("title", "")).strip()
    ]


def _build_document_outline_for_saved_technical_outline(
    project_id: int,
    technical_outline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project = _fetch_project(project_id)
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    if not parsed_json:
        return []
    requirements = TenderRequirements.model_validate(parsed_json)
    from services import template_service

    bid_template = (
        template_service.bid_template_for_project(project_id) or load_bid_template()
    )
    document_outline = build_bid_document_outline(requirements, bid_template)
    technical_children = [
        BidDocumentOutlineSection(
            title=item["title"],
            volume="技术标",
            section_type="construction_design",
            required=item["required"],
            source_item=item.get("source_item", ""),
            focus_points=item.get("focus_points", []),
        )
        for item in technical_outline
    ]
    for section in document_outline:
        if section.section_type in {"technical_volume", "construction_design"}:
            section.children = technical_children
    return [section.model_dump() for section in document_outline]


def save_selected_knowledge_chunks(
    project_id: int,
    selected_chunk_ids: list[int],
) -> dict[str, Any]:
    unique_ids = sorted({int(chunk_id) for chunk_id in selected_chunk_ids})
    references = get_knowledge_references(unique_ids)
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET selected_chunk_ids = %s
                WHERE id = %s
                RETURNING id, selected_chunk_ids
                """,
                (Json(unique_ids), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "selected_chunk_ids": row["selected_chunk_ids"] or [],
        "references": references,
    }


def get_knowledge_references(chunk_ids: list[int]) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    knowledge_chunks.id AS chunk_id,
                    knowledge_chunks.document_id,
                    knowledge_chunks.content,
                    knowledge_chunks.metadata,
                    documents.file_name,
                    documents.metadata_json
                FROM knowledge_chunks
                LEFT JOIN documents ON documents.id = knowledge_chunks.document_id
                WHERE knowledge_chunks.id = ANY(%s)
                ORDER BY knowledge_chunks.id
                """,
                (chunk_ids,),
            )
            rows = cursor.fetchall()
    return [
        {
            "chunk_id": int(row["chunk_id"]),
            "document_id": row["document_id"],
            "title": row["file_name"] or (row["metadata"] or {}).get("file_name", ""),
            "content": row["content"],
            "metadata": {
                **(row["metadata"] or {}),
                **(row["metadata_json"] or {}),
            },
        }
        for row in rows
    ]


def save_draft_markdown(project_id: int, markdown: str) -> dict[str, Any]:
    clean_markdown = markdown.strip()
    if not clean_markdown:
        raise ValueError("Draft markdown cannot be empty")
    project = _fetch_project(project_id)
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    if not parsed_json:
        raise ValueError("Project has no parsed requirements")
    report = review(TenderRequirements.model_validate(parsed_json), clean_markdown)
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET edited_markdown = %s,
                    review_report_json = %s,
                    status = %s
                WHERE id = %s
                RETURNING id, status, edited_markdown, review_report_json
                """,
                (
                    clean_markdown,
                    Json(report.model_dump()),
                    "draft_saved",
                    project_id,
                ),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    invalidate_delivery_preview_cache(project_id)
    return dict(row)


def build_project_pricing_strategy(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    requirements = _project_requirements(project)
    review_report = _project_review_report(project)
    strategy = extract_pricing_strategy(requirements)
    report = generate_pricing_strategy_report(strategy, review_report)

    with _connect() as conn:
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

    with _connect() as conn:
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

    with _connect() as conn:
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
    with _connect() as conn:
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
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET final_versions_json = %s WHERE id = %s",
                (Json(versions), project_id),
            )
    return versions


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


def _delivery_markdown_source(project: dict[str, Any]) -> str:
    markdown = project.get("edited_markdown") or (
        project.get("workflow_state_json") or {}
    ).get("draft_markdown", "")
    if markdown:
        return markdown
    object_name = project.get("generated_markdown_path")
    if not object_name:
        raise ValueError("尚未生成可拆分的 Markdown 源文件")
    return minio_client.download_bytes(settings.minio_bucket, object_name).decode(
        "utf-8"
    )


# Cache of the latest delivery preview per project, keyed by a fingerprint of
# the fields the preview is derived from. The fingerprint changes on any
# project write that affects the preview, so stale entries are never served;
# write paths in this module also invalidate eagerly.
_delivery_preview_cache: dict[int, tuple[str, dict[str, Any]]] = {}


def _delivery_preview_fingerprint(project: dict[str, Any]) -> str:
    workflow_state = project.get("workflow_state_json") or {}
    payload = json.dumps(
        {
            "status": project.get("status"),
            "edited_markdown": project.get("edited_markdown"),
            "draft_markdown": workflow_state.get("draft_markdown"),
            "draft_volumes": workflow_state.get("draft_volumes"),
            "generated_markdown_path": project.get("generated_markdown_path"),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def invalidate_delivery_preview_cache(project_id: int) -> None:
    _delivery_preview_cache.pop(project_id, None)


def get_project_delivery_preview(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    fingerprint = _delivery_preview_fingerprint(project)
    cached = _delivery_preview_cache.get(project_id)
    if cached and cached[0] == fingerprint:
        return cached[1]
    volumes = _delivery_volumes(project)
    response_volumes = {}
    for key, label in _DELIVERY_VOLUME_LABELS.items():
        markdown = volumes[key]
        response_volumes[key] = {
            "key": key,
            "label": label,
            "markdown": markdown,
            "line_count": len(markdown.splitlines()),
            "char_count": len(markdown),
        }
    preview = {
        "project_id": project["id"],
        "status": project["status"],
        "volumes": response_volumes,
    }
    _delivery_preview_cache[project_id] = (fingerprint, preview)
    return preview


def _delivery_volumes(project: dict[str, Any]) -> dict[str, str]:
    if project.get("edited_markdown"):
        return split_delivery_markdown(project["edited_markdown"])
    workflow_state = project.get("workflow_state_json") or {}
    draft_volumes = workflow_state.get("draft_volumes") or {}
    if draft_volumes:
        return {
            key: draft_volumes.get(key, "")
            or f"# {_DELIVERY_VOLUME_LABELS[key]}\n\n（本卷暂无内容，请人工补充。）"
            for key in _DELIVERY_VOLUME_LABELS
        }
    return split_delivery_markdown(_delivery_markdown_source(project))


def _project_review_report(project: dict[str, Any]) -> ReviewReport | None:
    return _review_report_from_json(project.get("review_report_json"))


def _review_report_from_json(payload: dict[str, Any] | None) -> ReviewReport | None:
    if not payload:
        return None
    return ReviewReport.model_validate(payload)


def _project_pricing_strategy(project: dict[str, Any]) -> PricingStrategy | None:
    payload = project.get("pricing_strategy_json")
    if not payload:
        return None
    return PricingStrategy.model_validate(payload)


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


_DOWNLOAD_ARTIFACTS = {
    "docx": ("合并投标 DOCX", "docx"),
    "pdf": ("合并投标 PDF", "pdf"),
    "markdown": ("Markdown 源文件", "md"),
    "review": ("审查报告", "md"),
}
_DELIVERY_VOLUME_LABELS = {
    "commercial": "商务文件",
    "technical": "技术文件",
    "pricing": "报价文件",
}
_DELIVERY_FORMATS = {"docx", "pdf"}


def get_project_download_url(
    project_id: int,
    artifact: str = "docx",
    expiry: int = 3600,
) -> dict[str, Any]:
    project = _fetch_project(project_id)
    artifact = (artifact or "docx").lower()
    label, suffix = _DOWNLOAD_ARTIFACTS.get(artifact, ("", ""))
    project_name = project.get("name") or "投标文件"
    version = len(project.get("final_versions_json") or []) or 1

    if artifact == "docx":
        object_name = project.get("generated_docx_path")
        if not object_name:
            raise ValueError("尚未生成可下载的标书文件")
        filename = build_export_filename(project_name, version, suffix=suffix)
    elif artifact == "pdf":
        object_name = _export_delivery_artifact(project, volume=None, suffix="pdf")
        filename = build_export_filename(project_name, version, suffix=suffix)
    elif artifact == "markdown":
        object_name = project.get("generated_markdown_path")
        if not object_name:
            raise ValueError("尚未生成可下载的 Markdown 文件")
        filename = build_export_filename(project_name, version, suffix=suffix)
    elif artifact == "review":
        object_name = _export_review_report(project)
        filename = build_export_filename(f"{project_name}_审查报告", version, suffix=suffix)
    else:
        volume, file_format = _parse_delivery_artifact(artifact)
        label = f"{_DELIVERY_VOLUME_LABELS[volume]} {file_format.upper()}"
        suffix = file_format
        object_name = _export_delivery_artifact(
            project,
            volume=volume,
            suffix=file_format,
        )
        filename = build_export_filename(
            project_name,
            version,
            kind=_DELIVERY_VOLUME_LABELS[volume],
            suffix=suffix,
        )

    return {
        "project_id": project["id"],
        "status": project["status"],
        "download_url": minio_client.get_presigned_url(
            settings.minio_bucket,
            object_name,
            expiry=expiry,
            response_filename=filename,
        ),
        "expires_in": expiry,
        "artifact": artifact,
        "artifact_label": label,
        "filename": filename,
    }


def _parse_delivery_artifact(artifact: str) -> tuple[str, str]:
    try:
        volume, file_format = artifact.rsplit("_", 1)
    except ValueError as error:
        raise ValueError(f"不支持的下载类型：{artifact}") from error
    if volume not in _DELIVERY_VOLUME_LABELS or file_format not in _DELIVERY_FORMATS:
        raise ValueError(f"不支持的下载类型：{artifact}")
    return volume, file_format


def _export_delivery_artifact(
    project: dict[str, Any],
    *,
    volume: str | None,
    suffix: str,
) -> str:
    markdown = _delivery_markdown_source(project)
    project_id = project["id"]
    title = project.get("name") or "投标文件"
    if volume:
        markdown = _delivery_volumes(project)[volume]
        label = _DELIVERY_VOLUME_LABELS[volume]
        object_name = f"projects/{project_id}/generated/delivery/{volume}.{suffix}"
        title = f"{title}（{label}）"
    else:
        object_name = f"projects/{project_id}/generated/delivery/combined.{suffix}"

    with TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / f"delivery.{suffix}"
        if suffix == "docx":
            markdown_to_docx(
                markdown,
                output_path,
                title=title,
                subtitle="投标文件",
                cover=True,
                toc=True,
                header_text=title,
                page_numbers=True,
                style_profile="zhengqi",
            )
        elif suffix == "pdf":
            markdown_to_pdf(markdown, output_path, title=title)
        else:
            raise ValueError(f"不支持的下载格式：{suffix}")
        minio_client.upload_file(settings.minio_bucket, output_path, object_name)
    return object_name


def _export_review_report(project: dict[str, Any]) -> str:
    """Render the review report to markdown, store it in MinIO, return its key."""
    report = project.get("review_report_json")
    if not report:
        raise ValueError("尚无审查报告可下载")
    markdown = _build_review_report_markdown(project)
    object_name = f"projects/{project['id']}/generated/review_report.md"
    minio_client.upload_file(
        settings.minio_bucket,
        markdown.encode("utf-8"),
        object_name,
    )
    return object_name


def _build_review_report_markdown(project: dict[str, Any]) -> str:
    report = project.get("review_report_json") or {}
    findings = report.get("findings", [])
    lines = [
        f"# 审查报告 - {project.get('name', '')}",
        "",
        f"- 通过项：{report.get('pass_count', 0)}",
        f"- 警告项：{report.get('warning_count', 0)}",
        f"- 失败项：{report.get('fail_count', 0)}",
        "",
        "## 审查明细",
        "",
    ]
    if not findings:
        lines.append("（暂无审查发现）")
    for finding in findings:
        lines.append(f"### [{finding.get('status', '')}] {finding.get('rule', '')}")
        lines.append(f"- 严重度：{finding.get('severity', '')}")
        if finding.get("suggestion"):
            lines.append(f"- 建议：{finding.get('suggestion')}")
        if finding.get("evidence"):
            lines.append(f"- 证据：{finding.get('evidence')}")
        lines.append("")
    return "\n".join(lines)


def get_project_review_report(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    workflow_state = project.get("workflow_state_json")
    project_status = project["status"]
    running_statuses = {"uploading", "parsing", "processing", "generating", "reviewing"}
    return {
        "project_id": project["id"],
        "status": (
            project_status
            if project_status in running_statuses
            else (workflow_state or {}).get("status") or project_status
        ),
        "review_report": project.get("review_report_json"),
        "workflow_state": workflow_state,
    }
