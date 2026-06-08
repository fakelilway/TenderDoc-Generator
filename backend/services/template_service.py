"""Bid template library (M64).

Admins upload historical bid PDFs which are parsed into a :class:`BidTemplate`
and stored with tags (project type, specialty, envelope type, region, year).
When a project is created the closest template can be recommended and the user
may switch the project's template manually. The generation pipeline prefers the
project's selected template over the default file-based one.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from schemas.bid_template import BidTemplate
from services.project_service import ProjectNotFoundError, _connect
from utils.bid_template_parser import parse_bid_template_bytes


class TemplateNotFoundError(Exception):
    """Raised when a template id is not present in the database."""


def _parse_template(file_bytes: bytes, filename: str, name: str) -> BidTemplate:
    """Parse uploaded bid bytes into a BidTemplate (PDF only for now)."""
    if not (filename or "").lower().endswith(".pdf"):
        raise ValueError("模板样本目前仅支持 PDF 格式的历史投标文件")
    if not file_bytes:
        raise ValueError("上传的模板文件为空")
    return parse_bid_template_bytes(
        file_bytes, source_file=filename, template_name=name or filename
    )


def _template_summary(row: dict[str, Any]) -> dict[str, Any]:
    template_json = row.get("template_json") or {}
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "source_filename": row.get("source_filename"),
        "project_type": row.get("project_type"),
        "specialty": row.get("specialty"),
        "envelope_type": row.get("envelope_type"),
        "region": row.get("region"),
        "project_year": row.get("project_year"),
        "tags": row.get("tags") or [],
        "project_name": template_json.get("project_name"),
        "page_count": template_json.get("page_count"),
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
    }


def create_template(
    file_bytes: bytes,
    filename: str,
    name: str,
    project_type: str | None = None,
    specialty: str | None = None,
    envelope_type: str | None = None,
    region: str | None = None,
    project_year: int | None = None,
    tags: list[str] | None = None,
    created_by: int | None = None,
) -> dict[str, Any]:
    clean_name = (name or "").strip() or (filename or "投标模板")
    template = _parse_template(file_bytes, filename, clean_name)
    # Fall back to structure detected from the document when tags are absent.
    envelope_type = envelope_type or template.envelope_type or None

    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO bid_templates (
                    name,
                    source_filename,
                    project_type,
                    specialty,
                    envelope_type,
                    region,
                    project_year,
                    tags,
                    template_json,
                    created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, source_filename, project_type, specialty,
                          envelope_type, region, project_year, tags,
                          template_json, created_by, created_at
                """,
                (
                    clean_name,
                    filename,
                    project_type,
                    specialty,
                    envelope_type,
                    region,
                    project_year,
                    Json(tags or []),
                    Json(template.model_dump(mode="json")),
                    created_by,
                ),
            )
            row = cursor.fetchone()
    return _template_summary(dict(row))


def list_templates() -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, name, source_filename, project_type, specialty,
                       envelope_type, region, project_year, tags,
                       template_json, created_by, created_at
                FROM bid_templates
                ORDER BY created_at DESC, id DESC
                """
            )
            rows = cursor.fetchall()
    return [_template_summary(dict(row)) for row in rows]


def _fetch_template_row(template_id: int) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, name, source_filename, project_type, specialty,
                       envelope_type, region, project_year, tags,
                       template_json, created_by, created_at
                FROM bid_templates
                WHERE id = %s
                """,
                (template_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise TemplateNotFoundError(f"Template {template_id} was not found")
    return dict(row)


def get_template(template_id: int) -> dict[str, Any]:
    return _template_summary(_fetch_template_row(template_id))


def update_template(
    template_id: int,
    name: str | None = None,
    project_type: str | None = None,
    specialty: str | None = None,
    envelope_type: str | None = None,
    region: str | None = None,
    project_year: int | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    current = _fetch_template_row(template_id)
    new_name = (name or "").strip() or current["name"]
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE bid_templates
                SET name = %s,
                    project_type = %s,
                    specialty = %s,
                    envelope_type = %s,
                    region = %s,
                    project_year = %s,
                    tags = %s
                WHERE id = %s
                RETURNING id, name, source_filename, project_type, specialty,
                          envelope_type, region, project_year, tags,
                          template_json, created_by, created_at
                """,
                (
                    new_name,
                    project_type if project_type is not None else current.get("project_type"),
                    specialty if specialty is not None else current.get("specialty"),
                    envelope_type if envelope_type is not None else current.get("envelope_type"),
                    region if region is not None else current.get("region"),
                    project_year if project_year is not None else current.get("project_year"),
                    Json(tags if tags is not None else (current.get("tags") or [])),
                    template_id,
                ),
            )
            row = cursor.fetchone()
    return _template_summary(dict(row))


def delete_template(template_id: int) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM bid_templates WHERE id = %s RETURNING id",
                (template_id,),
            )
            if cursor.fetchone() is None:
                raise TemplateNotFoundError(f"Template {template_id} was not found")


def _match_score(
    summary: dict[str, Any],
    project_type: str | None,
    specialty: str | None,
    envelope_type: str | None,
    region: str | None,
    project_year: int | None,
    project_name: str | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    criteria = (
        ("project_type", project_type, 3.0, "项目类型"),
        ("specialty", specialty, 2.0, "专业"),
        ("envelope_type", envelope_type, 1.5, "信封类型"),
        ("region", region, 1.0, "地区"),
    )
    for field, value, weight, label in criteria:
        if value and summary.get(field) and str(summary[field]).strip() == str(value).strip():
            score += weight
            reasons.append(f"{label}匹配：{value}")

    if project_year and summary.get("project_year"):
        diff = abs(int(summary["project_year"]) - int(project_year))
        if diff == 0:
            score += 1.0
            reasons.append(f"年份匹配：{project_year}")
        elif diff <= 2:
            score += 0.5
            reasons.append(f"年份接近：{summary['project_year']}")

    if project_name and summary.get("project_name"):
        similarity = SequenceMatcher(
            None, str(project_name), str(summary["project_name"])
        ).ratio()
        if similarity >= 0.4:
            score += round(similarity, 4)
            reasons.append(f"项目名相似度 {round(similarity, 2)}")

    # Tag overlap with provided project_type/specialty keywords.
    tags = {str(tag) for tag in (summary.get("tags") or [])}
    for value in (project_type, specialty, region):
        if value and value in tags:
            score += 0.5
            reasons.append(f"标签命中：{value}")

    return round(score, 4), reasons


def recommend_templates(
    project_type: str | None = None,
    specialty: str | None = None,
    envelope_type: str | None = None,
    region: str | None = None,
    project_year: int | None = None,
    project_name: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    summaries = list_templates()
    scored: list[dict[str, Any]] = []
    for summary in summaries:
        score, reasons = _match_score(
            summary,
            project_type,
            specialty,
            envelope_type,
            region,
            project_year,
            project_name,
        )
        scored.append(
            {"template": summary, "match_score": score, "match_reasons": reasons}
        )

    # Highest score first; ties keep the newest (list_templates is newest-first).
    scored.sort(key=lambda item: item["match_score"], reverse=True)
    return scored[:limit]


def bid_template_for_project(project_id: int) -> BidTemplate | None:
    """Return the BidTemplate selected for a project, if any."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT t.template_json AS template_json
                FROM projects p
                JOIN bid_templates t ON t.id = p.template_id
                WHERE p.id = %s
                """,
                (project_id,),
            )
            row = cursor.fetchone()
    if not row or not row.get("template_json"):
        return None
    try:
        return BidTemplate.model_validate(row["template_json"])
    except Exception:
        return None


def set_project_template(project_id: int, template_id: int | None) -> dict[str, Any]:
    """Switch (or clear) the template attached to a project."""
    if template_id is not None:
        _fetch_template_row(template_id)  # validate existence
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET template_id = %s
                WHERE id = %s
                RETURNING id, template_id
                """,
                (template_id, project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {"project_id": int(row["id"]), "template_id": row["template_id"]}
