from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from agents.parser_agent import parse_tender
from core.config import settings
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
    return {
        "project_id": project["id"],
        "status": project["status"],
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
        "parsed_json": project["parsed_json"],
    }


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
    return {
        "project_id": project["id"],
        "status": project["status"],
        "review_report": project.get("review_report_json"),
        "workflow_state": project.get("workflow_state_json"),
    }
