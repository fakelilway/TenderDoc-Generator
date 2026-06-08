from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from psycopg2.extras import Json, RealDictCursor

from agents.generator_agent import (
    build_bid_outline,
    generate_bid_document,
    load_bid_template,
)
from core.config import settings
from rag import retriever
from schemas.bid import BidGenerationResult
from schemas.tender import TenderRequirements
from services.project_service import ProjectNotFoundError, _connect
from utils.docx_exporter import markdown_to_docx
from utils.minio_client import minio_client


PLACEHOLDER_WORDS = ("待补充", "TODO", "占位", "placeholder")


def generate_and_export(project_id: int) -> BidGenerationResult:
    project = _fetch_project_for_generation(project_id)
    parsed_json = project.get("parsed_json")
    if not parsed_json:
        raise ValueError("Project has no parsed tender requirements")

    requirements = TenderRequirements.model_validate(parsed_json)
    from services import template_service

    bid_template = (
        template_service.bid_template_for_project(project_id) or load_bid_template()
    )
    outline = build_bid_outline(requirements, bid_template)
    retrieved_chunks_by_section = {
        section.title: retriever.retrieve(
            _section_query(section.title, requirements), top_k=3
        )
        for section in outline
    }

    with _status(project_id, "generating"):
        markdown = generate_bid_document(
            requirements, retrieved_chunks_by_section, bid_template
        )
        quality_report = evaluate_generation_quality(markdown)
        markdown_object, docx_object = export_markdown_for_project(
            project_id,
            markdown,
            quality_report,
        )

    return BidGenerationResult(
        outline=outline,
        markdown=markdown,
        generated_markdown_path=markdown_object,
        generated_docx_path=docx_object,
        quality_report=quality_report,
    )


def export_markdown_for_project(
    project_id: int,
    markdown: str,
    quality_report: dict[str, float | int],
) -> tuple[str, str]:
    title = _extract_markdown_title(markdown) or "投标文件"
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        markdown_path = tmp_path / f"project_{project_id}_bid.md"
        docx_path = tmp_path / f"project_{project_id}_bid.docx"
        markdown_path.write_text(markdown, encoding="utf-8")
        markdown_to_docx(
            markdown,
            docx_path,
            title=title,
            subtitle="投标文件",
            cover=True,
            toc=True,
            header_text=title,
            page_numbers=True,
            style_profile="zhengqi",
        )

        markdown_object = f"projects/{project_id}/generated/bid.md"
        docx_object = f"projects/{project_id}/generated/bid.docx"
        minio_client.upload_file(settings.minio_bucket, markdown_path, markdown_object)
        minio_client.upload_file(settings.minio_bucket, docx_path, docx_object)

    _update_generation_paths(
        project_id,
        markdown_object,
        docx_object,
        quality_report,
    )
    return markdown_object, docx_object


def evaluate_generation_quality(markdown_text: str) -> dict[str, float | int]:
    paragraphs = [
        line.strip()
        for line in markdown_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    total = len(paragraphs)
    needs_revision = 0
    for paragraph in paragraphs:
        lower = paragraph.lower()
        if len(paragraph) < 20 or any(
            word.lower() in lower for word in PLACEHOLDER_WORDS
        ):
            needs_revision += 1

    usable = max(total - needs_revision, 0)
    usable_rate = usable / total if total else 0.0
    return {
        "total_paragraphs": total,
        "needs_revision_paragraphs": needs_revision,
        "usable_paragraphs": usable,
        "usable_rate": round(usable_rate, 4),
    }


def _fetch_project_for_generation(project_id: int) -> dict:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, name, parsed_json
                FROM projects
                WHERE id = %s
                """,
                (project_id,),
            )
            row = cursor.fetchone()

    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return dict(row)


def _update_generation_paths(
    project_id: int,
    markdown_path: str,
    docx_path: str,
    quality_report: dict[str, float | int],
) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET
                    generated_markdown_path = %s,
                    generated_docx_path = %s,
                    generation_quality_json = %s,
                    status = %s
                WHERE id = %s
                """,
                (
                    markdown_path,
                    docx_path,
                    Json(quality_report),
                    "generated",
                    project_id,
                ),
            )


def _set_status(project_id: int, status: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET status = %s WHERE id = %s",
                (status, project_id),
            )


def start_generation(project_id: int, background_tasks) -> dict[str, str]:
    task_id = uuid4().hex
    _set_status(project_id, "processing")
    background_tasks.add_task(_run_background_generation, project_id)
    return {"task_id": task_id, "status": "processing"}


def _run_background_generation(project_id: int) -> None:
    try:
        generate_and_export(project_id)
    except Exception:
        _set_status(project_id, "generation_failed")


class _status:
    def __init__(self, project_id: int, status: str) -> None:
        self.project_id = project_id
        self.status = status

    def __enter__(self):
        _set_status(self.project_id, self.status)

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            _set_status(self.project_id, "generation_failed")
        return False


def _extract_markdown_title(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return None


def _section_query(section_title: str, requirements: TenderRequirements) -> str:
    descriptions = [
        item.description
        for item in requirements.technical_score_items
        if section_title in item.title or item.title in section_title
    ]
    if not descriptions:
        descriptions = [
            item.description for item in requirements.technical_score_items[:2]
        ]
    return (
        "历史投标文件 施工组织设计 技术措施 正式标书措辞 素材参考 "
        f"{requirements.project_name} {section_title} {' '.join(descriptions)}"
    )
