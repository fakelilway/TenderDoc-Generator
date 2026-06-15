"""Tender parsing pipeline: start, parse, confirm parsed result."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from core.config import settings
from schemas.tender import TenderRequirements
from utils.file_parser import extract_text

from . import _runtime
from ._helpers import _fetch_project, _parse_workflow_state
from ._helpers import _workflow_patch
from .errors import ProjectNotFoundError


def parse_project(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    if not project["tender_file_path"]:
        raise ValueError("Project has no tender file path")
    if project.get("parsed_json"):
        return project

    with _runtime.connect() as conn:
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
                "UPDATE projects SET status = %s, workflow_state_json = %s WHERE id = %s",
                (
                    "parsing",
                    Json(
                        _parse_workflow_state(
                            project_id,
                            "parsing",
                            "running",
                            "解析 Agent 正在读取招标文件并调用 LLM。",
                        )
                    ),
                    project_id,
                ),
            )

    try:
        file_bytes = _runtime.minio().download_bytes(
            settings.minio_bucket,
            str(document["file_path"]),
        )
        text = extract_text(
            file_bytes,
            filename=str(document["file_name"]),
            content_type=document["file_type"],
        )
        parsed = _runtime.parse_tender(text)
        parsed_json = parsed.model_dump()
        status = "parsed"
    except Exception as error:
        with _runtime.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE projects SET status = %s, workflow_state_json = %s WHERE id = %s",
                    (
                        "failed",
                        Json(
                            _parse_workflow_state(
                                project_id, "failed", "failed", f"解析失败：{error}"
                            )
                        ),
                        project_id,
                    ),
                )
        raise

    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET parsed_json = %s,
                    tender_text = %s,
                    workflow_state_json = %s,
                    status = %s
                WHERE id = %s
                RETURNING id, name, tender_file_path, parsed_json, status, created_at
                """,
                (
                    Json(parsed_json),
                    text,
                    Json(
                        _parse_workflow_state(
                            project_id,
                            "parsed",
                            "done",
                            "招标文件已解析完成，结构化要求已保存。",
                            parsed_json,
                        )
                    ),
                    status,
                    project_id,
                ),
            )
            return dict(cursor.fetchone())


def start_parse_project(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    if not project["tender_file_path"]:
        raise ValueError("Project has no tender file path")
    if project.get("parsed_json"):
        return project
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET status = %s,
                    workflow_state_json = %s
                WHERE id = %s
                RETURNING id, name, tender_file_path, parsed_json, status, created_at
                """,
                (
                    "parsing",
                    Json(
                        _parse_workflow_state(
                            project_id, "parsing", "running", "解析任务已启动，正在后台处理。"
                        )
                    ),
                    project_id,
                ),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return dict(row)


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
    confirmed_model = TenderRequirements.model_validate(parsed_json)
    confirmed = confirmed_model.model_dump()
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET confirmed_parsed_json = %s,
                    parsed_json = %s,
                    workflow_state_json = COALESCE(workflow_state_json, '{}'::jsonb) || %s::jsonb,
                    status = %s
                WHERE id = %s
                RETURNING id, status, confirmed_parsed_json
                """,
                (
                    Json(confirmed),
                    Json(confirmed),
                    Json(
                        _workflow_patch(
                            project_id,
                            "parsed_confirmed",
                            parsed=confirmed,
                        )
                    ),
                    "parsed_confirmed",
                    project_id,
                ),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return dict(row)
