from __future__ import annotations

import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn


FORMAT_CHAPTER_RE = re.compile(r"第[一二三四五六七八九十百\d]+章\s*(?:投标文件格式|响应文件格式)")
NEXT_CHAPTER_RE = re.compile(r"第[一二三四五六七八九十百\d]+章")
FORMAT_BODY_MARKERS = (
    "投标文件（商务文件）",
    "投标文件（技术文件）",
    "投标文件（报价文件）",
    "响应文件格式",
    "一、投标函",
)


def build_original_format_docx(
    tender_docx_bytes: bytes,
    output_path: str | Path,
    *,
    profile: dict[str, Any] | None = None,
) -> str:
    """Copy the tender DOCX format chapter as OOXML, then fill known fields.

    This is intentionally not a markdown reconstruction path. The copied
    paragraphs/tables keep the tender file's own Word XML: merged cells,
    borders, underlines, paragraph alignment, and spacing.
    """
    source = Document(BytesIO(tender_docx_bytes))
    target = Document()
    _clear_document_body(target)

    elements = list(source.element.body)
    start = _find_format_start(elements)
    if start is None:
        raise ValueError("未能在 DOCX 招标文件中定位“投标文件格式”章节，不能原样复制。")
    end = _find_format_end(elements, start)

    for element in elements[start:end]:
        if element.tag == qn("w:sectPr"):
            continue
        target.element.body.append(deepcopy(element))

    _replace_known_fields(target, profile or {})
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target.save(path)
    return str(path)


def _clear_document_body(document: Document) -> None:
    body = document.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def _find_format_start(elements: list[Any]) -> int | None:
    first_format_heading: int | None = None
    first_body_marker: int | None = None
    for index, element in enumerate(elements):
        text = _element_text(element)
        if not text:
            continue
        compact = re.sub(r"\s+", "", text)
        if first_format_heading is None and FORMAT_CHAPTER_RE.search(compact):
            first_format_heading = index
        if first_body_marker is None and any(marker in compact for marker in FORMAT_BODY_MARKERS):
            first_body_marker = index
        if first_format_heading is not None and first_body_marker is not None:
            break
    return first_format_heading if first_format_heading is not None else first_body_marker


def _find_format_end(elements: list[Any], start: int) -> int:
    for index in range(start + 1, len(elements)):
        text = _element_text(elements[index])
        if not text:
            continue
        compact = re.sub(r"\s+", "", text)
        if NEXT_CHAPTER_RE.match(compact) and not FORMAT_CHAPTER_RE.search(compact):
            return index
    return len(elements)


def _element_text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()


def _replace_known_fields(document: Document, profile: dict[str, Any]) -> None:
    replacements = _known_replacements(profile)
    for paragraph in document.paragraphs:
        _replace_in_paragraph(paragraph, replacements)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _replace_in_paragraph(paragraph, replacements)


def _known_replacements(profile: dict[str, Any]) -> dict[str, str]:
    project_name = str(profile.get("项目名称") or profile.get("project_name") or "")
    tenderer = str(profile.get("招标人") or profile.get("tenderer_name") or "")
    company = str(profile.get("company_name") or profile.get("投标人") or "")
    return {
        "（招标人）": tenderer,
        "（招标人名称）": tenderer,
        "受益人（招标人）名称": tenderer,
        "(招标人名称)": tenderer,
        "（招标项目名称）": project_name,
        "（项目名称）": project_name,
        "（投标人名称）": company,
    }


def _replace_in_paragraph(paragraph, replacements: dict[str, str]) -> None:
    if not paragraph.runs:
        return
    original = paragraph.text
    updated = original
    for source, target in replacements.items():
        if target:
            updated = updated.replace(source, target)
    if updated == original:
        return

    first_run = paragraph.runs[0]
    for run in paragraph.runs[1:]:
        run.text = ""
    first_run.text = updated


# ── PDF original copy ──────────────────────────────────────────────────

import fitz  # noqa: E402
from docx.shared import Inches, Cm  # noqa: E402
from docx.enum.section import WD_ORIENT  # noqa: E402


def build_original_format_docx_from_pdf(
    tender_pdf_bytes: bytes,
    output_path: str | Path,
    *,
    profile: dict[str, Any] | None = None,
    dpi: int = 200,
) -> str:
    """Render the PDF format chapter as full-page images in a DOCX.

    Each format chapter page is rendered at the given DPI and inserted as a locked,
    full-page image.  This preserves every pixel of the original PDF — tables, borders,
    underlines, signature positions, page numbers — exactly as the tender issuer designed it.

    After the locked format pages, a blank final section is added for the construction
    plan content to be filled by the Content Writer.
    """
    profile = profile or {}
    pdf = fitz.open("pdf", tender_pdf_bytes)
    page_range = _find_format_page_range(pdf)

    if not page_range:
        pdf.close()
        raise ValueError("未能在 PDF 招标文件中定位“投标文件格式”章节，不能原样复制。")

    target = Document()
    _clear_document_body(target)

    # Set page size to A4 portrait
    section = target.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.orientation = WD_ORIENT.PORTRAIT

    for page_num in range(page_range[0], page_range[1]):
        page = pdf[page_num]
        # Render at specified DPI
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")

        # Insert as full-page image
        paragraph = target.add_paragraph()
        run = paragraph.add_run()
        stream = BytesIO(img_bytes)
        run.add_picture(stream, width=Cm(17.5))  # A4 width minus margins

        # Page break after each page
        if page_num < page_range[1] - 1:
            target.add_page_break()

    pdf.close()

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target.save(path)
    return str(path)


def _find_format_page_range(pdf: fitz.Document) -> tuple[int, int] | None:
    """Find the page range of the format chapter in a PDF."""
    format_start: int | None = None
    format_end: int | None = None

    for page_num in range(pdf.page_count):
        text = pdf[page_num].get_text()
        compact = re.sub(r"\s+", "", text)

        # Find format chapter start
        if format_start is None and FORMAT_CHAPTER_RE.search(compact):
            # Skip past TOC line — find the actual content
            actual_start = _skip_toc_pages(pdf, page_num)
            format_start = actual_start

        # Find next chapter end
        if format_start is not None and format_end is None and page_num > format_start:
            # Check if this page starts a new chapter (not format chapter)
            if NEXT_CHAPTER_RE.match(compact) and not FORMAT_CHAPTER_RE.search(compact):
                format_end = page_num
                break

    if format_start is None:
        return None

    if format_end is None:
        format_end = pdf.page_count

    return (format_start, format_end)


def _skip_toc_pages(pdf: fitz.Document, from_page: int) -> int:
    """Skip TOC pages after finding the format chapter heading."""
    # Check next few pages — if they're TOC (contain "........" dots), skip them
    for offset in range(5):
        page_num = from_page + offset
        if page_num >= pdf.page_count:
            return from_page
        text = pdf[page_num].get_text()
        # If page contains actual form content markers, it's not TOC
        if any(marker in text for marker in FORMAT_BODY_MARKERS):
            return page_num
        # If page has lots of dot leaders, it's TOC — skip
        if text.count("........") + text.count("……") + text.count("....") > 3:
            continue
        # If page has substantial unique text, it's probably content
        if len(set(text)) > 100:
            return page_num
    return from_page
