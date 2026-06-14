from __future__ import annotations

import logging
import re
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg2.extras import Json

from core.config import settings
from schemas.tender import TenderRequirements
from services.company_profile_service import get_company_profile
from services.original_docx_format_service import (
    PDF_PAGE_MARKER_PREFIX,
    build_original_format_docx,
    _clear_document_body as _clear_body,
)
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
            _split_and_export_volumes(
                original_format_path, tmp_path, project_id, markdown
            )
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


def _split_and_export_volumes(
    format_path: str,
    tmp_path: Path,
    project_id: int,
    markdown: str,
) -> None:
    """Split a merged format DOCX into three independent volume DOCX files
    at OOXML element level, preserving tables, borders, and formatting."""
    import re, shutil
    from docx import Document as _D
    from docx.oxml.ns import qn

    from utils.docx_exporter import split_delivery_markdown

    src = _D(format_path)
    body = src.element.body
    elements = list(body)
    volumes = split_delivery_markdown(markdown)
    technical_markdown = volumes.get("technical", "")
    commercial_markdown = volumes.get("commercial", "")

    if _split_pdf_page_blocks(elements, body, tmp_path, project_id, technical_markdown, commercial_markdown):
        return

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
                _append_prose_to_docx(vol_path, technical_markdown)
            elif vol == "commercial":
                _append_prose_to_docx(vol_path, commercial_markdown)
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
            doc.element.body.append(deepcopy(el))
        vol_path = tmp_path / f"project_{project_id}_{vol}.docx"
        # Copy section properties from source
        for el in body:
            if el.tag == qn("w:sectPr"):
                doc.element.body.append(deepcopy(el))
                break
        doc.save(str(vol_path))
        if vol == "technical":
            _append_prose_to_docx(vol_path, technical_markdown)
        elif vol == "commercial":
            _append_prose_to_docx(vol_path, commercial_markdown)


def _split_pdf_page_blocks(
    elements: list,
    body,
    tmp_path: Path,
    project_id: int,
    technical_markdown: str,
    commercial_markdown: str = "",
) -> bool:
    """Split our PDF-copy DOCX by whole page blocks instead of raw elements."""
    from docx import Document as _D

    blocks = _collect_pdf_page_blocks(elements)
    if not blocks:
        return False

    sections: dict[str, list] = {"commercial": [], "technical": [], "pricing": []}
    current_vol = "commercial"
    for block in blocks:
        block_text = _docx_block_text(block)
        current_vol = _classify_pdf_page_volume(block_text, current_vol)
        sections[current_vol].extend(el for el in block if not _is_pdf_page_marker(el))

    for vol in ("commercial", "technical", "pricing"):
        doc = _D()
        _clear_body(doc)
        for el in sections.get(vol, []):
            doc.element.body.append(deepcopy(el))
        _append_source_section_props(doc, body)
        vol_path = tmp_path / f"project_{project_id}_{vol}.docx"
        doc.save(str(vol_path))
        if vol == "technical":
            _append_prose_to_docx(vol_path, technical_markdown)
        elif vol == "commercial" and commercial_markdown:
            _append_prose_to_docx(vol_path, commercial_markdown)
    return True


def _collect_pdf_page_blocks(elements: list) -> list[list]:
    blocks: list[list] = []
    current: list | None = None
    pending_section_breaks: list = []

    for el in elements:
        if _is_pdf_page_marker(el):
            if current:
                blocks.append(current)
            current = [*pending_section_breaks, el]
            pending_section_breaks = []
            continue

        if current is None:
            continue

        if _is_section_break_only(el):
            pending_section_breaks.append(el)
            continue

        if pending_section_breaks:
            current.extend(pending_section_breaks)
            pending_section_breaks = []
        current.append(el)

    if current:
        current.extend(pending_section_breaks)
        blocks.append(current)
    return blocks


def _docx_block_text(elements: list) -> str:
    return "".join(_docx_element_text(el) for el in elements)


def _docx_element_text(element) -> str:
    from docx.oxml.ns import qn

    return "".join(node.text or "" for node in element.iter(qn("w:t")))


def _is_pdf_page_marker(element) -> bool:
    return _docx_element_text(element).startswith(PDF_PAGE_MARKER_PREFIX)


def _is_section_break_only(element) -> bool:
    from docx.oxml.ns import qn

    if element.tag == qn("w:sectPr"):
        return True
    if element.tag != qn("w:p"):
        return False
    has_section = element.find(f".//{qn('w:sectPr')}") is not None
    has_text = bool(_docx_element_text(element).strip())
    has_drawing = element.find(f".//{qn('w:drawing')}") is not None
    has_pict = element.find(f".//{qn('w:pict')}") is not None
    return has_section and not has_text and not has_drawing and not has_pict


def _classify_pdf_page_volume(text: str, current: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    head = compact[:220]
    candidates = {
        "commercial": (
            "投标文件（商务文件）",
            "响应文件（商务文件）",
            "商务文件目录",
            "商务文件",
            "商务标",
        ),
        "technical": (
            "投标文件（技术文件）",
            "响应文件（技术文件）",
            "技术文件目录",
            "技术文件",
            "技术标",
            "施工组织设计",
        ),
        "pricing": (
            "投标文件（报价文件）",
            "响应文件（报价文件）",
            "报价文件目录",
            "报价文件",
            "报价标",
            "已标价工程量清单",
            "第二信封",
        ),
    }
    best: tuple[int, str] | None = None
    for volume, markers in candidates.items():
        for marker in markers:
            position = head.find(marker)
            if position == -1:
                continue
            if best is None or position < best[0]:
                best = (position, volume)
    return best[1] if best is not None else current


def _append_source_section_props(doc, body) -> None:
    from docx.oxml.ns import qn

    for child in list(doc.element.body):
        if child.tag == qn("w:sectPr"):
            doc.element.body.remove(child)
    for el in body:
        if el.tag == qn("w:sectPr"):
            doc.element.body.append(deepcopy(el))
            return
