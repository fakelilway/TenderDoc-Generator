from __future__ import annotations

import logging
import os
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
    markdown = strip_meta_notes(markdown)
    title = _extract_markdown_title(markdown) or "投标文件"
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        markdown_path = tmp_path / f"project_{project_id}_bid.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        docx_path = tmp_path / f"project_{project_id}_bid.docx"

        if original_format_path and Path(original_format_path).exists():
            # Split format DOCX into three independent volume files at OOXML level
            _split_and_export_volumes(original_format_path, tmp_path, project_id, markdown)
            # Main docx = technical (has prose)
            import shutil
            shutil.copy2(tmp_path / f"project_{project_id}_technical.docx", docx_path)
        elif not _try_export_original_docx_format(project_id, docx_path):
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
                    settings.minio_bucket, vol_path,
                    f"projects/{project_id}/generated/{vol}.docx"
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
        profile.update({
            "project_name": parsed.get("project_name") or tender.get("name") or "",
            "项目名称": parsed.get("project_name") or tender.get("name") or "",
            "tenderer_name": parsed.get("tenderer_name") or "",
            "招标人": parsed.get("tenderer_name") or "",
        })
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
    """Append prose content after format pages in a DOCX."""
    from docx import Document
    from docx.shared import Pt

    doc = Document(str(docx_path))
    doc.add_page_break()

    lines = prose_markdown.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('# '):
            p = doc.add_paragraph()
            run = p.add_run(line[2:].strip())
            run.bold = True
            run.font.size = Pt(16)
        elif line.startswith('## '):
            p = doc.add_paragraph()
            run = p.add_run(line[3:].strip())
            run.bold = True
            run.font.size = Pt(14)
        else:
            doc.add_paragraph(line)

    doc.save(str(docx_path))


def _split_and_export_volumes(
    format_path: str,
    tmp_path: Path,
    project_id: int,
    prose: str,
) -> None:
    """Split a merged format DOCX into three independent volume DOCX files
    at OOXML element level, preserving tables, borders, and formatting."""
    import re, shutil
    from docx import Document as _D
    from docx.oxml.ns import qn

    src = _D(format_path)
    body = src.element.body
    elements = list(body)

    # Volume boundary patterns (look for section headings that mark volume divisions)
    VOL_BOUNDARIES = {
        "commercial": re.compile(r"商务文件|商务标|商务及技术"),
        "technical": re.compile(r"技术文件|施工组织|技术标"),
        "pricing": re.compile(r"报价文件|报价标|已标价工程量清单|第二信封"),
    }

    # Initialize with all elements going to commercial by default
    sections: dict[str, list] = {"commercial": [], "technical": [], "pricing": []}

    # Determine volume boundaries by finding first occurrence of each marker
    boundaries: list[tuple[int, str]] = []
    for i, el in enumerate(elements):
        text = "".join(node.text or "" for node in el.iter(qn("w:t")))
        for vol, pat in VOL_BOUNDARIES.items():
            if pat.search(text) and not any(b[1] == vol for b in boundaries):
                boundaries.append((i, vol))
                break
    boundaries.sort()

    # Assign elements to volumes based on boundaries
    if not boundaries:
        # No boundaries found — copy everything to all volumes
        for vol in ("commercial", "technical", "pricing"):
            vol_path = tmp_path / f"project_{project_id}_{vol}.docx"
            shutil.copy2(format_path, vol_path)
            if vol == "technical":
                _append_prose_to_docx(vol_path, prose)
        return

    # Build volume element lists
    current_vol = "commercial"
    boundary_idx = 0
    for i, el in enumerate(elements):
        if el.tag == qn("w:sectPr"):
            continue
        while boundary_idx < len(boundaries) and i >= boundaries[boundary_idx][0]:
            current_vol = boundaries[boundary_idx][1]
            boundary_idx += 1
        sections[current_vol].append(el)

    # Create three DOCX files with deepcopy of elements
    for vol in ("commercial", "technical", "pricing"):
        doc = _D()
        _clear_body(doc)
        for el in sections.get(vol, []):
            doc.element.body.append(__import__('copy').deepcopy(el))
        vol_path = tmp_path / f"project_{project_id}_{vol}.docx"
        # Copy section properties from source
        for el in body:
            if el.tag == qn("w:sectPr"):
                doc.element.body.append(__import__('copy').deepcopy(el))
                break
        doc.save(str(vol_path))
        if vol == "technical":
            _append_prose_to_docx(vol_path, prose)


def _clear_body(doc: 'Document') -> None:
    """Remove all children from document body except sectPr."""
    from docx.oxml.ns import qn as _qn
    for child in list(doc.element.body):
        if child.tag != _qn("w:sectPr"):
            doc.element.body.remove(child)
