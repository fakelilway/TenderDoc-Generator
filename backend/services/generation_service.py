from __future__ import annotations

import logging
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg2.extras import Json

from core.config import settings
from schemas.tender import TenderRequirements
from services.company_profile_service import get_company_profile
from services.original_docx_format_service import build_original_format_docx
from services.project_service import _connect
from utils.docx_exporter import markdown_to_docx, strip_meta_notes
from utils.minio_client import minio_client


logger = logging.getLogger(__name__)

PLACEHOLDER_WORDS = ("待补充", "TODO", "占位", "placeholder")


def export_markdown_for_project(
    project_id: int,
    markdown: str,
    quality_report: dict[str, float | int],
    *,
    original_format_path: str | None = None,
) -> tuple[str, str]:
    # Keep volume markers intact for splitting; strip meta/markers only for the
    # human-readable bid.md and the non-format whole-doc render. Stripping before
    # the split would drop the tdg:volume markers → split falls back to a heading
    # heuristic that leaks commercial sections into the technical volume.
    clean_markdown = strip_meta_notes(markdown)
    title = _extract_markdown_title(clean_markdown) or "投标文件"
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        markdown_path = tmp_path / f"project_{project_id}_bid.md"
        markdown_path.write_text(clean_markdown, encoding="utf-8")
        docx_path = tmp_path / f"project_{project_id}_bid.docx"

        if original_format_path and Path(original_format_path).exists():
            # 两卷装配：商务=整本格式章照抄(整页图+填空字段，copy2 保留图片),
            # 技术=LLM 正文独立成文，报价=外部造价软件不产出。
            # 不再按页块三卷拆分——格式章即商务卷，硬拆会错分页面、丢图片。
            _assemble_two_volumes(
                original_format_path, tmp_path, project_id, markdown, docx_path, title
            )
        elif not _try_export_original_docx_format(project_id, docx_path):
            markdown_to_docx(
                clean_markdown,
                docx_path,
                title=title,
                subtitle="投标文件",
                cover=True,
                toc=True,
                header_text=title,
                page_numbers=True,
                style_profile="zhengqi",
                image_resolver=_resolve_knowledge_image,
            )

        markdown_object = f"projects/{project_id}/generated/bid.md"
        docx_object = f"projects/{project_id}/generated/bid.docx"
        minio_client.upload_file(settings.minio_bucket, markdown_path, markdown_object)
        minio_client.upload_file(settings.minio_bucket, docx_path, docx_object)

        # Upload three independent volume DOCX files
        for vol in ("commercial", "technical", "pricing"):
            vol_path = tmp_path / f"project_{project_id}_{vol}.docx"
            if vol_path.exists():
                minio_client.upload_file(
                    settings.minio_bucket,
                    vol_path,
                    f"projects/{project_id}/generated/{vol}.docx",
                )

    _update_generation_paths(
        project_id,
        markdown_object,
        docx_object,
        quality_report,
    )
    return markdown_object, docx_object


def _try_export_original_docx_format(project_id: int, docx_path: Path) -> bool:
    try:
        tender = _fetch_tender_document(project_id)
    except Exception:
        logger.exception("Tender document lookup unavailable; using markdown export")
        return False
    if not tender:
        return False
    filename = str(tender.get("file_name") or "")
    object_name = str(tender.get("file_path") or "")
    if not filename.lower().endswith(".docx"):
        return False
    try:
        tender_bytes = minio_client.download_bytes(settings.minio_bucket, object_name)
        profile = _export_profile_from_tender(tender)
        build_original_format_docx(tender_bytes, docx_path, profile=profile)
        return True
    except Exception:
        logger.exception("Original DOCX format export failed")
        raise ValueError("DOCX 招标文件原格式复制失败，系统不会回退生成近似格式文件。")


def _fetch_tender_document(project_id: int) -> dict[str, object] | None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.file_name, d.file_path, p.name, p.confirmed_parsed_json, p.parsed_json
                FROM projects p
                LEFT JOIN documents d
                    ON d.project_id = p.id AND d.file_path = p.tender_file_path
                WHERE p.id = %s
                ORDER BY d.id DESC
                LIMIT 1
                """,
                (project_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return row
    keys = ("file_name", "file_path", "name", "confirmed_parsed_json", "parsed_json")
    return dict(zip(keys, row))


def _export_profile_from_tender(tender: dict[str, object]) -> dict[str, object]:
    parsed = tender.get("confirmed_parsed_json") or tender.get("parsed_json") or {}
    profile: dict[str, object] = {}
    if isinstance(parsed, dict):
        profile.update(
            {
                "project_name": parsed.get("project_name") or tender.get("name") or "",
                "项目名称": parsed.get("project_name") or tender.get("name") or "",
                "tenderer_name": parsed.get("tenderer_name") or "",
                "招标人": parsed.get("tenderer_name") or "",
                "工期": parsed.get("planned_duration") or "",
                "质量": parsed.get("quality_standard") or "",
                "安全": parsed.get("safety_target") or "",
                "投标有效期": parsed.get("bid_deadline") or "",
                "投标截止时间": parsed.get("bid_deadline") or "",
            }
        )
    try:
        company_profile = get_company_profile().get("profile", {})
        if isinstance(company_profile, dict):
            profile.update(company_profile)
    except Exception:
        logger.warning("Company profile unavailable during original DOCX export")
    return profile


def evaluate_generation_quality(markdown_text: str) -> dict[str, float | int]:
    paragraphs = [
        line.strip()
        for line in markdown_text.splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
        and not _is_markdown_table_control_line(line)
        and not line.strip().startswith("{{knowledge_image:")
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


def _extract_markdown_title(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return None


def _image_reference_query(requirements: TenderRequirements) -> str:
    descriptions = [
        item.description
        for item in [
            *requirements.qualification_list,
            *requirements.technical_score_items,
            *requirements.invalid_bid_items,
        ]
    ]
    return (
        f"{requirements.project_name} 营业执照 资质证书 安全生产许可证 "
        "建造师 身份证 建安证 交安证 职称证 社保 业绩 施工平面图 " + " ".join(descriptions)
    )


def _resolve_knowledge_image(document_id: int) -> bytes | None:
    from services import knowledge_service

    try:
        return knowledge_service.get_knowledge_document_file_bytes(document_id)
    except Exception:
        logger.exception(
            "Failed to resolve knowledge image bytes for document %s", document_id
        )
        return None


def _is_markdown_table_control_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _append_prose_to_docx(docx_path: Path, prose_markdown: str) -> None:
    """Append prose content after format pages in a DOCX.

    Uses the full markdown_to_docx renderer which correctly handles
    headings (H1–H3), markdown tables, tdg:pagebreak markers,
    underlined blanks, and the zhengqi style profile (SimSun 14pt,
    SimHei headings, 32pt line spacing).
    """
    if not prose_markdown.strip():
        return

    from utils.docx_exporter import _render_markdown_body, _configure_styles
    from docx import Document

    # Render prose markdown into a temporary DOCX, then copy its
    # body elements into the format DOCX.
    doc = Document(str(docx_path))
    _configure_styles(doc, "zhengqi")
    doc.add_page_break()
    _render_markdown_body(doc, prose_markdown, "zhengqi")
    doc.save(str(docx_path))


def _assemble_two_volumes(
    format_path: str,
    tmp_path: Path,
    project_id: int,
    markdown: str,
    main_docx_path: Path,
    title: str,
) -> None:
    """Two-volume delivery for editable format docs (pdf2docx / DOCX 照抄).

    - 商务卷 = the converted format chapter, copied verbatim (照抄) with known
      fields already filled, then appended compliance prose if any.
    - 技术卷 = the LLM-written prose as its OWN zhengqi-styled document (cover +
      TOC), never glued onto the commercial format pages.
    - 报价卷 = done externally in造价软件; this system does NOT produce it.

    The main bid.docx mirrors the technical volume (the part with written prose).
    """
    import shutil

    from utils.docx_exporter import split_delivery_markdown

    volumes = split_delivery_markdown(markdown)
    commercial_markdown = volumes.get("commercial", "")
    technical_markdown = volumes.get("technical", "") or markdown

    # 商务卷：照抄格式章 + 合规正文
    commercial_path = tmp_path / f"project_{project_id}_commercial.docx"
    shutil.copy2(format_path, commercial_path)
    if commercial_markdown.strip():
        _append_prose_to_docx(commercial_path, commercial_markdown)

    # 技术卷：独立成文的施工组织设计正文
    technical_path = tmp_path / f"project_{project_id}_technical.docx"
    if technical_markdown.strip():
        markdown_to_docx(
            technical_markdown,
            technical_path,
            title=title,
            subtitle="技术文件",
            cover=True,
            toc=True,
            header_text=title,
            page_numbers=True,
            style_profile="zhengqi",
            image_resolver=_resolve_knowledge_image,
        )
    else:
        shutil.copy2(format_path, technical_path)

    shutil.copy2(technical_path, main_docx_path)

