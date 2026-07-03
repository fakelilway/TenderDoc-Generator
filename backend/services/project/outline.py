"""Outline building/saving, knowledge chunk selection, and draft markdown."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import (
    build_bid_document_outline,
    build_bid_outline,
)
from agents.reviewer_agent import review
from schemas.bid import BidDocumentOutlineSection
from schemas.tender import TenderRequirements

from . import _runtime
from ._helpers import _fetch_project, _workflow_patch
from .delivery import invalidate_delivery_preview_cache
from .errors import ProjectNotFoundError


def build_project_outline(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    if not parsed_json:
        raise ValueError("Project has no parsed requirements")
    requirements = TenderRequirements.model_validate(parsed_json)
    outline = [
        section.model_dump()
        for section in build_bid_outline(requirements)
    ]
    document_outline = [
        section.model_dump()
        for section in build_bid_document_outline(requirements)
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
                "manual_image_slots": _clean_manual_image_slots(
                    item.get("manual_image_slots", [])
                ),
            }
        )
    clean_document_outline = (
        _clean_document_outline(document_outline)
        if document_outline
        else _build_document_outline_for_saved_technical_outline(
            project_id, clean_outline
        )
    )
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET bid_outline_json = %s,
                    document_outline_json = %s,
                    workflow_state_json = COALESCE(workflow_state_json, '{}'::jsonb) || %s::jsonb,
                    status = %s
                WHERE id = %s
                RETURNING id, status, bid_outline_json, document_outline_json
                """,
                (
                    Json(clean_outline),
                    Json(clean_document_outline),
                    Json(
                        _workflow_patch(
                            project_id,
                            status,
                            bid_outline=clean_outline,
                            document_outline=clean_document_outline,
                        )
                    ),
                    status,
                    project_id,
                ),
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


def _clean_manual_image_slots(slots: Any) -> list[dict[str, str]]:
    if not isinstance(slots, list):
        return []
    clean_slots: list[dict[str, str]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        title = str(slot.get("title") or "").strip()
        placement = str(slot.get("placement") or "").strip()
        description = str(slot.get("description") or "").strip()
        if not title and not placement and not description:
            continue
        clean_slots.append(
            {
                "title": title,
                "placement": placement,
                "description": description,
            }
        )
    return clean_slots


def _build_document_outline_for_saved_technical_outline(
    project_id: int,
    technical_outline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project = _fetch_project(project_id)
    parsed_json = project.get("confirmed_parsed_json") or project.get("parsed_json")
    if not parsed_json:
        return []
    requirements = TenderRequirements.model_validate(parsed_json)
    document_outline = build_bid_document_outline(requirements)
    technical_children = [
        BidDocumentOutlineSection(
            title=item["title"],
            volume="技术标",
            section_type="construction_design",
            required=item["required"],
            source_item=item.get("source_item", ""),
            focus_points=item.get("focus_points", []),
            manual_image_slots=item.get("manual_image_slots", []),
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
    with _runtime.connect() as conn:
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
    with _runtime.connect() as conn:
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
    with _runtime.connect() as conn:
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
