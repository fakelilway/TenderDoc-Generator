from __future__ import annotations

import logging
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg2.extras import Json

from core.config import settings
from schemas.tender import TenderRequirements
from services.company_profile_service import get_company_profile
from services.original_docx_format_service import (
    PDF_PAGE_MARKER_PREFIX,
    build_original_format_docx,
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


def _format_doc_has_page_markers(format_path) -> bool:
    """True when the format DOCX is the image-fallback path (hidden PDF page markers)."""
    from docx import Document as _D

    try:
        doc = _D(str(format_path))
    except Exception:
        return False
    return PDF_PAGE_MARKER_PREFIX in doc.element.xml


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


def _split_and_export_volumes(
    format_path: str,
    tmp_path: Path,
    project_id: int,
    markdown: str,
) -> None:
    """Split an image-fallback format DOCX (hidden PDF page markers) into volume
    files by whole page blocks. Editable 照抄 docs use _assemble_two_volumes."""
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

    if _split_pdf_page_blocks(elements, body, format_path, tmp_path, project_id, technical_markdown, commercial_markdown):
        return

    # Keyword boundary heuristic (only reached for marker-less docs passed directly).
    VOL_BOUNDARIES = {
        "commercial": re.compile(r"商务文件|商务标|商务及技术"),
        "technical": re.compile(r"技术文件|施工组织|技术标"),
        "pricing": re.compile(r"报价文件|报价标|已标价工程量清单|第二信封"),
    }
    sections: dict[str, list] = {"commercial": [], "technical": [], "pricing": []}
    boundaries: list[tuple[int, str]] = []
    for i, el in enumerate(elements):
        text = "".join(node.text or "" for node in el.iter(qn("w:t")))
        norm = re.sub(r"\s+", "", text)
        # Only short, heading-like lines are real volume dividers. A keyword that
        # appears inside the 目录 or a body sentence (e.g. "愿以报价文件投标函中的
        # 报价…") must NOT be treated as a boundary — that mis-routed whole volumes.
        if not (0 < len(norm) <= 16):
            continue
        for vol, pat in VOL_BOUNDARIES.items():
            if pat.search(norm) and not any(b[1] == vol for b in boundaries):
                boundaries.append((i, vol))
                break
    boundaries.sort()

    if not boundaries:
        # No tree and no reliable dividers — the format chapter has no separable
        # volumes (common: chapter is commercial-only; 技术 is self-authored,
        # 报价 工程量清单 is a separate workbook). Put everything in commercial and
        # leave the other volumes for their own pipelines, rather than duplicating
        # or mis-routing. Flag for human review.
        logger.warning(
            "Volume split found no outline tree and no reliable dividers — "
            "treating format chapter as commercial-only (project %s)",
            project_id,
        )
        sections = {"commercial": list(elements), "technical": [], "pricing": []}
        _write_volumes_by_pruning(
            format_path, _vol_by_child_index(elements, _id_to_vol(sections)),
            tmp_path, project_id, technical_markdown, commercial_markdown,
        )
        return

    current_vol = "commercial"
    boundary_idx = 0
    for i, el in enumerate(elements):
        if el.tag == qn("w:sectPr"):
            continue
        while boundary_idx < len(boundaries) and i >= boundaries[boundary_idx][0]:
            current_vol = boundaries[boundary_idx][1]
            boundary_idx += 1
        sections[current_vol].append(el)

    _write_volumes_by_pruning(
        format_path, _vol_by_child_index(elements, _id_to_vol(sections)),
        tmp_path, project_id, technical_markdown, commercial_markdown,
    )


def _id_to_vol(sections: dict[str, list]) -> dict[int, str]:
    """Map each assigned element's identity → its volume."""
    return {id(el): vol for vol, els in sections.items() for el in els}


def _vol_by_child_index(elements: list, id_to_vol: dict[int, str]) -> dict[int, str | None]:
    """Map body-child position (excluding sectPr) → volume, for copy-then-prune.

    Positions match the source DOCX reopened from disk, so pruning preserves
    image parts/relationships that deepcopy-into-a-fresh-Document would drop.
    """
    from docx.oxml.ns import qn

    mapping: dict[int, str | None] = {}
    index = 0
    for el in elements:
        if el.tag == qn("w:sectPr"):
            continue
        mapping[index] = id_to_vol.get(id(el))  # None → drop (e.g. page markers)
        index += 1
    return mapping


def _write_volumes_by_pruning(
    source_path: str,
    vol_by_index: dict[int, str | None],
    tmp_path: Path,
    project_id: int,
    technical_markdown: str,
    commercial_markdown: str,
) -> None:
    """Write the three volume DOCX by copying the source (keeps embedded images
    and their relationships) then removing the body children not in that volume.

    Building a fresh Document and deepcopy-ing elements drops image parts —
    delivered volumes then render blank. Copy-then-prune avoids that.
    """
    import shutil

    from docx import Document as _D
    from docx.oxml.ns import qn

    for vol in ("commercial", "technical", "pricing"):
        vol_path = tmp_path / f"project_{project_id}_{vol}.docx"
        has_pages = any(v == vol for v in vol_by_index.values())
        if has_pages:
            # Copy source (keeps embedded images + relationships), then prune
            # body children not belonging to this volume.
            shutil.copy2(source_path, vol_path)
            doc = _D(str(vol_path))
            body = doc.element.body
            index = 0
            for child in list(body):
                if child.tag == qn("w:sectPr"):
                    continue
                keep = vol_by_index.get(index) == vol
                index += 1
                if not keep:
                    body.remove(child)
            doc.save(str(vol_path))
        else:
            # No format pages for this volume → fresh empty doc, not a 3MB copy
            # of the source (which would carry unreferenced image bloat).
            _D().save(str(vol_path))
        if vol == "technical":
            _append_prose_to_docx(vol_path, technical_markdown)
        elif vol == "commercial" and commercial_markdown:
            _append_prose_to_docx(vol_path, commercial_markdown)



def _split_pdf_page_blocks(
    elements: list,
    body,
    source_path: str,
    tmp_path: Path,
    project_id: int,
    technical_markdown: str,
    commercial_markdown: str = "",
) -> bool:
    """Split our PDF-copy DOCX by whole page blocks, preserving embedded images.

    Uses copy-then-prune (see _write_volumes_by_pruning) so the full-page form
    images survive into the delivered volumes; page markers are dropped.
    """
    blocks = _collect_pdf_page_blocks(elements)
    if not blocks:
        return False

    id_to_vol: dict[int, str] = {}
    current_vol = "commercial"
    for block in blocks:
        current_vol = _classify_pdf_page_volume(_docx_block_text(block), current_vol)
        for el in block:
            if not _is_pdf_page_marker(el):
                id_to_vol[id(el)] = current_vol

    _write_volumes_by_pruning(
        source_path, _vol_by_child_index(elements, id_to_vol),
        tmp_path, project_id, technical_markdown, commercial_markdown,
    )
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


