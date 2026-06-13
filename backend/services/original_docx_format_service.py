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
) -> str:
    """Convert the PDF format chapter to DOCX with full table/layout preservation.

    Uses pdf2docx for true paragraph/table/font conversion — not image embedding.
    Tables become real DOCX tables, paragraphs keep alignment, and we replace
    known placeholder text (招标人, 项目名称, etc.) after conversion.
    """
    import tempfile
    from pdf2docx import Converter

    profile = profile or {}

    # Write PDF bytes to temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        tmp_pdf.write(tender_pdf_bytes)
        pdf_path = tmp_pdf.name

    try:
        # Find format chapter page range
        page_range = _find_format_page_range_in_pdf(pdf_path)
        if not page_range:
            raise ValueError("未能在 PDF 中定位“投标文件格式”章节")

        # Convert using pdf2docx
        cv = Converter(pdf_path)
        cv.convert(str(output_path), start=page_range[0], end=page_range[1])
        cv.close()

        # Replace known placeholders in the resulting DOCX
        _replace_known_fields_in_docx(output_path, profile)

        return str(output_path)
    finally:
        import os
        try:
            os.unlink(pdf_path)
        except OSError:
            pass


def _find_format_page_range_in_pdf(pdf_path: str) -> tuple[int, int] | None:
    """Find format chapter page range using the last occurrence of the heading."""
    doc = fitz.open(pdf_path)
    try:
        # Find ALL occurrences of the format chapter heading — use the LAST one
        # (PDFs often have a TOC reference early; the actual chapter body is later)
        matches: list[int] = []
        for page_num in range(doc.page_count):
            text = doc[page_num].get_text()
            compact = re.sub(r"\s+", "", text)
            if FORMAT_CHAPTER_RE.search(compact):
                matches.append(page_num)

        if not matches:
            return None

        # Use the last match as the actual chapter start
        format_start = matches[-1]
        # Skip TOC pages following the chapter heading
        format_start = _skip_toc_pages(doc, format_start)

        # Find the end: next chapter heading that's NOT the format chapter
        format_end = doc.page_count
        for page_num in range(format_start + 1, doc.page_count):
            text = doc[page_num].get_text()
            compact = re.sub(r"\s+", "", text)
            if NEXT_CHAPTER_RE.match(compact) and not FORMAT_CHAPTER_RE.search(compact):
                format_end = page_num
                break

        return (format_start + 1, format_end + 1)  # 1-based for pdf2docx
    finally:
        doc.close()


def _replace_known_fields_in_docx(docx_path: str | Path, profile: dict[str, Any]) -> None:
    """Replace placeholder text throughout a DOCX (paragraphs AND tables)."""
    from docx import Document
    doc = Document(str(docx_path))
    _replace_known_fields(doc, profile)
    doc.save(str(docx_path))


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
