"""Project CRUD, listing, status polling, ownership and authorization."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import RealDictCursor

from core.config import settings

from . import _runtime
from ._helpers import (
    _fetch_project,
    _fetch_project_status,
    _project_summary,
    _resolve_project_status,
    _safe_filename,
)
from .delivery import invalidate_delivery_preview_cache
from .errors import ProjectNotFoundError, ProjectAccessError


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

    with _runtime.connect() as conn:
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

            object_name = _runtime.tender_object_name(project["id"], filename)
            _runtime.minio().upload_file(settings.minio_bucket, file_bytes, object_name)

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
    with _runtime.connect() as conn:
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
    owner_id = _runtime.get_project_owner(project_id)
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
                _runtime.minio().remove_file(settings.minio_bucket, object_key)
            except Exception:
                pass
    # Clean up volume DOCX files and delivery artifacts
    for vol in ("commercial", "technical", "pricing"):
        vol_key = f"projects/{project_id}/generated/{vol}.docx"
        try:
            _runtime.minio().remove_file(settings.minio_bucket, vol_key)
        except Exception:
            pass

    with _runtime.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    invalidate_delivery_preview_cache(project_id)


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
    with _runtime.connect() as conn:
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
        "status": _resolve_project_status(
            project_status,
            project["workflow_status"],
        ),
        "parsed": bool(project["parsed"]),
    }
