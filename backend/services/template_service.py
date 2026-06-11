"""Bid template library (M64).

Admins upload historical bid PDFs which are parsed into a :class:`BidTemplate`
and stored with tags (project type, specialty, envelope type, region, year).
When a project is created the closest template can be recommended and the user
may switch the project's template manually. The generation pipeline prefers the
project's selected template over the default file-based one.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from agents.template_profile_agent import build_template_profile
from schemas.bid_template import BidTemplate
from schemas.template_profile import TemplateProfile
from services.project_service import ProjectNotFoundError, _connect
from utils.bid_template_parser import parse_bid_template_bytes


DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "bid_templates"
    / "road_first_envelope_template.json"
)


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
    profile_json = row.get("template_profile_json") or {}
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
        "has_profile": bool(profile_json),
        "profile_generated_by": profile_json.get("generated_by"),
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
    profile = build_template_profile(
        template,
        project_type=project_type,
        specialty=specialty,
    )

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
                    template_profile_json,
                    created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, source_filename, project_type, specialty,
                          envelope_type, region, project_year, tags,
                          template_json, template_profile_json, created_by, created_at
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
                    Json(profile.model_dump(mode="json")),
                    created_by,
                ),
            )
            row = cursor.fetchone()
    return _template_summary(dict(row))


def seed_template_from_json(
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    name: str | None = None,
    project_type: str | None = "公路工程",
    specialty: str | None = "道路",
    envelope_type: str | None = None,
    region: str | None = None,
    project_year: int | None = None,
    tags: list[str] | None = None,
    created_by: int | None = None,
) -> dict[str, Any]:
    """Idempotently import a checked-in BidTemplate JSON into the DB library."""
    path = Path(template_path)
    template = BidTemplate.model_validate_json(path.read_text(encoding="utf-8"))
    clean_name = (name or template.template_name or path.stem).strip()
    source_filename = template.source_file or path.name
    clean_tags = tags if tags is not None else ["默认模板", "公路", "第一信封"]
    clean_envelope = envelope_type or template.envelope_type or None
    profile = build_template_profile(
        template,
        project_type=project_type,
        specialty=specialty,
    )

    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, name, source_filename, project_type, specialty,
                       envelope_type, region, project_year, tags,
                       template_json, template_profile_json, created_by, created_at
                FROM bid_templates
                WHERE source_filename = %s OR name = %s
                ORDER BY id ASC
                LIMIT 1
                """,
                (source_filename, clean_name),
            )
            row = cursor.fetchone()
            if row:
                existing = dict(row)
                if not existing.get("template_profile_json"):
                    cursor.execute(
                        """
                        UPDATE bid_templates
                        SET template_profile_json = %s
                        WHERE id = %s
                        RETURNING id, name, source_filename, project_type, specialty,
                                  envelope_type, region, project_year, tags,
                                  template_json, template_profile_json,
                                  created_by, created_at
                        """,
                        (Json(profile.model_dump(mode="json")), existing["id"]),
                    )
                    existing = dict(cursor.fetchone())
                return {**_template_summary(existing), "seeded": False}

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
                    template_profile_json,
                    created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, source_filename, project_type, specialty,
                          envelope_type, region, project_year, tags,
                          template_json, template_profile_json, created_by, created_at
                """,
                (
                    clean_name,
                    source_filename,
                    project_type,
                    specialty,
                    clean_envelope,
                    region,
                    project_year,
                    Json(clean_tags),
                    Json(template.model_dump(mode="json")),
                    Json(profile.model_dump(mode="json")),
                    created_by,
                ),
            )
            inserted = cursor.fetchone()
    return {**_template_summary(dict(inserted)), "seeded": True}


def list_templates() -> list[dict[str, Any]]:
    # Summary columns only: the full template_json/template_profile_json blobs
    # can be large and are not needed to build list summaries.
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, name, source_filename, project_type, specialty,
                       envelope_type, region, project_year, tags,
                       template_json->>'project_name' AS project_name,
                       (template_json->>'page_count')::int AS page_count,
                       (
                           template_profile_json IS NOT NULL
                           AND template_profile_json NOT IN ('{}'::jsonb, 'null'::jsonb)
                       ) AS has_profile,
                       template_profile_json->>'generated_by' AS profile_generated_by,
                       created_by, created_at
                FROM bid_templates
                ORDER BY created_at DESC, id DESC
                """
            )
            rows = cursor.fetchall()
    return [_summary_from_columns(dict(row)) for row in rows]


def _summary_from_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Build a summary from rows that already select the summary columns."""
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
        "project_name": row.get("project_name"),
        "page_count": row.get("page_count"),
        "has_profile": bool(row.get("has_profile")),
        "profile_generated_by": row.get("profile_generated_by"),
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
    }


def _fetch_template_row(template_id: int) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, name, source_filename, project_type, specialty,
                       envelope_type, region, project_year, tags,
                       template_json, template_profile_json, created_by, created_at
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
    new_project_type = (
        project_type if project_type is not None else current.get("project_type")
    )
    new_specialty = specialty if specialty is not None else current.get("specialty")
    profile_json = current.get("template_profile_json")
    if current.get("template_json"):
        try:
            profile_json = build_template_profile(
                BidTemplate.model_validate(current["template_json"]),
                project_type=new_project_type,
                specialty=new_specialty,
            ).model_dump(mode="json")
        except Exception:
            profile_json = current.get("template_profile_json")
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
                    tags = %s,
                    template_profile_json = %s
                WHERE id = %s
                RETURNING id, name, source_filename, project_type, specialty,
                          envelope_type, region, project_year, tags,
                          template_json, template_profile_json, created_by, created_at
                """,
                (
                    new_name,
                    new_project_type,
                    new_specialty,
                    envelope_type
                    if envelope_type is not None
                    else current.get("envelope_type"),
                    region if region is not None else current.get("region"),
                    project_year
                    if project_year is not None
                    else current.get("project_year"),
                    Json(tags if tags is not None else (current.get("tags") or [])),
                    Json(profile_json) if profile_json else None,
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
        if (
            value
            and summary.get(field)
            and str(summary[field]).strip() == str(value).strip()
        ):
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


def template_profile_for_project(project_id: int) -> TemplateProfile | None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT t.template_profile_json AS template_profile_json,
                       t.template_json AS template_json,
                       t.project_type,
                       t.specialty
                FROM projects p
                JOIN bid_templates t ON t.id = p.template_id
                WHERE p.id = %s
                """,
                (project_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    try:
        if row.get("template_profile_json"):
            return TemplateProfile.model_validate(row["template_profile_json"])
        if row.get("template_json"):
            template = BidTemplate.model_validate(row["template_json"])
            return build_template_profile(
                template,
                project_type=row.get("project_type"),
                specialty=row.get("specialty"),
            )
    except Exception:
        return None
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
