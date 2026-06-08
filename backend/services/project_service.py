from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import build_bid_outline, load_bid_template
from agents.parser_agent import parse_tender
from agents.reviewer_agent import review
from core.config import settings
from schemas.tender import TenderRequirements
from utils.file_parser import extract_text
from utils.minio_client import minio_client


class ProjectNotFoundError(Exception):
    """Raised when a project id is not present in the database."""


def _connect():
    if settings.database_url:
        return psycopg2.connect(settings.database_url)

    return psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


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
                    parsed_json,
                    generated_markdown_path,
                    generated_docx_path,
                    generation_quality_json,
                    review_report_json,
                    workflow_state_json,
                    confirmed_parsed_json,
                    bid_outline_json,
                    selected_chunk_ids,
                    edited_markdown,
                    final_checklist_json,
                    final_versions_json,
                    status,
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


def create_project(
    name: str,
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
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
                INSERT INTO projects (name, status)
                VALUES (%s, %s)
                RETURNING id, name, tender_file_path, parsed_json, status, created_at
                """,
                (safe_name, "uploading"),
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


def get_project_status(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    workflow_state = project.get("workflow_state_json") or {}
    project_status = project["status"]
    running_statuses = {"uploading", "parsing", "processing", "generating", "reviewing"}
    return {
        "project_id": project["id"],
        "status": (
            project_status
            if project_status in running_statuses
            else workflow_state.get("status") or project_status
        ),
        "parsed": project["parsed_json"] is not None,
    }


def parse_project(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    if not project["tender_file_path"]:
        raise ValueError("Project has no tender file path")

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
                SET parsed_json = %s, status = %s
                WHERE id = %s
                RETURNING id, name, tender_file_path, parsed_json, status, created_at
                """,
                (Json(parsed_json), status, project_id),
            )
            return dict(cursor.fetchone())


def get_project_result(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    return {
        "project_id": project["id"],
        "status": project["status"],
        "parsed_json": project.get("confirmed_parsed_json") or project["parsed_json"],
    }


def confirm_parsed_result(project_id: int, parsed_json: dict[str, Any]) -> dict[str, Any]:
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
    outline = [
        section.model_dump()
        for section in build_bid_outline(requirements, load_bid_template())
    ]
    return save_project_outline(project_id, outline, status="outline_ready")


def save_project_outline(
    project_id: int,
    outline: list[dict[str, Any]],
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
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET bid_outline_json = %s,
                    status = %s
                WHERE id = %s
                RETURNING id, status, bid_outline_json
                """,
                (Json(clean_outline), status, project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return dict(row)


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
    return dict(row)


def build_final_checklist(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json") or {}
    review_report = project.get("review_report_json") or {}
    markdown = project.get("edited_markdown") or (
        project.get("workflow_state_json") or {}
    ).get("draft_markdown", "")
    checklist = {
        "invalid_bid_responses": _checklist_items(
            parsed_json.get("invalid_bid_items", []),
            review_report,
            markdown,
        ),
        "manual_confirmation_points": _manual_confirmation_points(markdown),
        "pricing_manual_fields": _pricing_manual_fields(markdown),
        "attachment_list": _attachment_list(parsed_json),
    }
    versions = project.get("final_versions_json") or []
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET final_checklist_json = %s
                WHERE id = %s
                RETURNING id, final_checklist_json, final_versions_json
                """,
                (Json(checklist), project_id),
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


def _checklist_items(
    invalid_items: list[dict[str, Any]],
    review_report: dict[str, Any],
    markdown: str,
) -> list[dict[str, Any]]:
    findings = review_report.get("findings", [])
    return [
        {
            "title": item.get("title", "废标风险"),
            "requirement": item.get("description", ""),
            "status": _matching_status(item, findings),
            "responded": bool(item.get("description", "")[:12] in markdown or findings),
            "manual_confirmed": False,
        }
        for item in invalid_items
    ]


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


def _manual_confirmation_points(markdown: str) -> list[str]:
    return [
        line.strip()
        for line in markdown.splitlines()
        if "人工确认点" in line
    ]


def _pricing_manual_fields(markdown: str) -> list[str]:
    keywords = ("报价", "清单", "金额", "单价", "投标总价")
    return [
        line.strip()
        for line in _manual_confirmation_points(markdown)
        if any(keyword in line for keyword in keywords)
    ]


def _attachment_list(parsed_json: dict[str, Any]) -> list[str]:
    titles = [item.get("title", "") for item in parsed_json.get("qualification_list", [])]
    defaults = ["营业执照", "资质证书", "安全生产许可证", "项目经理证书", "业绩证明"]
    return [title for title in titles if title] or defaults


def get_project_review(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    parsed_json = project["parsed_json"] or {}
    return {
        "project_id": project["id"],
        "status": project["status"],
        "invalid_bid_items": parsed_json.get("invalid_bid_items", []),
        "review_report": project.get("review_report_json"),
    }


def get_project_download_url(project_id: int, expiry: int = 3600) -> dict[str, Any]:
    project = _fetch_project(project_id)
    generated_docx_path = project.get("generated_docx_path")
    if not generated_docx_path:
        raise ValueError("Project has no generated document to download")

    return {
        "project_id": project["id"],
        "status": project["status"],
        "download_url": minio_client.get_presigned_url(
            settings.minio_bucket,
            generated_docx_path,
            expiry=expiry,
        ),
        "expires_in": expiry,
    }


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
