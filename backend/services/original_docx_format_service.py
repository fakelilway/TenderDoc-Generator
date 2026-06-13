from __future__ import annotations

import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import parse_xml
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

# Maximum pages to scan after a chapter heading for TOC content
MAX_TOC_PAGES = 5
PDF_RENDER_DPI = 200
PDF_TEXT_LAYER_MAX_SPANS_PER_PAGE = 900
PDF_PAGE_MARKER_PREFIX = "TDG_PDF_PAGE_START"
PDF_PAGE_MARKER_TEXT_LIMIT = 6000


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
        if first_body_marker is None and any(
            marker in compact for marker in FORMAT_BODY_MARKERS
        ):
            first_body_marker = index
        if first_format_heading is not None and first_body_marker is not None:
            break
    return (
        first_format_heading if first_format_heading is not None else first_body_marker
    )


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
    if not any(replacements.values()):
        return  # No non-empty replacement targets — skip iteration entirely
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
    """Replace placeholder text while preserving per-run formatting.

    Instead of collapsing all runs into the first run (which destroys bold,
    italic, font size, etc.), this function performs replacements within
    each run individually. If a placeholder spans multiple runs, we fall
    back to paragraph-level replacement only for that specific placeholder.
    """
    if not paragraph.runs:
        return
    original = paragraph.text
    updated = original
    for source, target in replacements.items():
        if target:
            updated = updated.replace(source, target)
    if updated == original:
        return

    # Try per-run replacement first to preserve formatting
    changed = False
    for run in paragraph.runs:
        run_text = run.text
        new_text = run_text
        for source, target in replacements.items():
            if target:
                new_text = new_text.replace(source, target)
        if new_text != run_text:
            run.text = new_text
            changed = True

    if changed and paragraph.text == updated:
        return  # Per-run replacement succeeded — formatting preserved

    # Fallback: a placeholder spans multiple runs; collapse into first run
    first_run = paragraph.runs[0]
    for run in paragraph.runs[1:]:
        run.text = ""
    first_run.text = updated


# ── PDF original copy ──────────────────────────────────────────────────
# fitz (PyMuPDF) is imported lazily inside functions to avoid the ~2s module
# load overhead when only the DOCX path is used.


def build_original_format_docx_from_pdf(
    tender_pdf_bytes: bytes,
    output_path: str | Path,
    *,
    profile: dict[str, Any] | None = None,
) -> str:
    """Copy PDF format pages into DOCX with a faithful image base and text layer.

    PDF has no editable Word XML to deep-copy. The only reliable "原样" path is
    visual page copying: render each format-page at high DPI and place it on a
    Word page with matching dimensions. To keep it editable, we also place PDF
    text spans back onto the page as Word text boxes at their source
    coordinates. This deliberately avoids table/paragraph reconstruction,
    because reconstructed layouts can drift from the tender's required layout.
    """
    import tempfile
    from docx.shared import Pt
    import fitz

    # Write PDF bytes to temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        tmp_pdf.write(tender_pdf_bytes)
        pdf_path = tmp_pdf.name

    try:
        # Find format chapter page range
        page_range = _find_format_page_range_in_pdf(pdf_path)
        if not page_range:
            raise ValueError("未能在 PDF 中定位“投标文件格式”章节")

        pdf = fitz.open(pdf_path)
        try:
            docx = Document()
            _clear_document_body(docx)
            for index, page_num in enumerate(range(page_range[0], page_range[1])):
                page = pdf[page_num]
                if index == 0:
                    section = docx.sections[0]
                else:
                    section = docx.add_section()
                _match_section_to_pdf_page(section, page)
                _append_pdf_page_marker(docx, page_num, page.get_text())

                pix = page.get_pixmap(
                    matrix=fitz.Matrix(PDF_RENDER_DPI / 72, PDF_RENDER_DPI / 72),
                    alpha=False,
                )
                image_stream = BytesIO(pix.tobytes("png"))
                paragraph = docx.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                run = paragraph.add_run()
                run.add_picture(image_stream, width=section.page_width)
                _add_pdf_text_layer(docx, page, page_num)
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            docx.save(path)
        finally:
            pdf.close()
        return str(output_path)
    finally:
        import os

        try:
            os.unlink(pdf_path)
        except OSError:
            pass


def _find_format_page_range_in_pdf(pdf_path: str) -> tuple[int, int] | None:
    """Find zero-based, end-exclusive format chapter page range."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        # Extract all page texts once — avoids re-extraction per page
        page_texts: list[str] = [
            doc[page_num].get_text() for page_num in range(doc.page_count)
        ]
        page_compacts: list[str] = [re.sub(r"\s+", "", text) for text in page_texts]

        # Find ALL occurrences of the format chapter heading — use the LAST one
        # (PDFs often have a TOC reference early; the actual chapter body is later)
        matches: list[int] = []
        for page_num, compact in enumerate(page_compacts):
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
            compact = page_compacts[page_num]
            if _looks_like_next_chapter_page(compact):
                format_end = page_num
                break

        return (format_start, max(format_start + 1, format_end))
    finally:
        doc.close()


def _looks_like_next_chapter_page(compact_text: str) -> bool:
    """Detect a new chapter near the start of a PDF page.

    PDF extraction often prefixes a page number or header before the chapter
    heading, so strict ``match`` misses real boundaries. Limiting the search to
    the first part of the page avoids cutting on body references.
    """
    head = compact_text[:160]
    return bool(NEXT_CHAPTER_RE.search(head) and not FORMAT_CHAPTER_RE.search(head))


def _match_section_to_pdf_page(section: Any, page: Any) -> None:
    """Make a Word section match a PDF page before inserting its image."""
    from docx.shared import Pt

    rect = page.rect
    section.page_width = Pt(rect.width)
    section.page_height = Pt(rect.height)
    section.left_margin = Pt(0)
    section.right_margin = Pt(0)
    section.top_margin = Pt(0)
    section.bottom_margin = Pt(0)
    section.header_distance = Pt(0)
    section.footer_distance = Pt(0)


def _add_pdf_text_layer(document: Document, page: Any, page_num: int) -> None:
    """Overlay editable text boxes using PDF span coordinates.

    The rendered page image remains the visual authority. The text layer is for
    selection/editing/searching and should not be used to redraw tables.
    """
    spans = _extract_pdf_text_spans(page)
    for index, span in enumerate(spans[:PDF_TEXT_LAYER_MAX_SPANS_PER_PAGE]):
        _append_body_element(document, _editable_textbox_xml(span, page_num, index))


def _append_pdf_page_marker(document: Document, page_num: int, text: str) -> None:
    """Insert an invisible marker before each copied PDF page.

    Export later splits the copied format DOCX into 商务/技术/报价 files. Without
    a page-level marker, OOXML element splitting can separate a page image from
    its editable text boxes. The marker carries hidden page text so the splitter
    can move the whole page as one block.
    """
    compact_text = re.sub(r"\s+", "", text or "")[:PDF_PAGE_MARKER_TEXT_LIMIT]
    marker = f"{PDF_PAGE_MARKER_PREFIX}:{page_num}:{compact_text}"
    _append_body_element(document, _hidden_marker_xml(marker))


def _hidden_marker_xml(text: str) -> Any:
    escaped = escape(text)
    xml = f"""
    <w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr>
      <w:r>
        <w:rPr><w:vanish/></w:rPr>
        <w:t xml:space="preserve">{escaped}</w:t>
      </w:r>
    </w:p>
    """
    return parse_xml(xml)


def _extract_pdf_text_spans(page: Any) -> list[dict[str, Any]]:
    data = page.get_text("dict")
    spans: list[dict[str, Any]] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                if not text:
                    continue
                x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                width = max(float(x1) - float(x0), 2.0)
                height = max(float(y1) - float(y0), float(span.get("size") or 9) + 2.0)
                spans.append(
                    {
                        "text": text,
                        "left_pt": float(x0),
                        "top_pt": float(y0),
                        "width_pt": width,
                        "height_pt": height,
                        "font_size_pt": max(float(span.get("size") or 9), 6.0),
                    }
                )
    return spans


def _editable_textbox_xml(span: dict[str, Any], page_num: int, index: int) -> Any:
    text = escape(str(span["text"]))
    shape_id = f"tdg_pdf_text_{page_num}_{index}"
    left = _pt(span["left_pt"])
    top = _pt(span["top_pt"])
    width = _pt(span["width_pt"] + 2)
    height = _pt(span["height_pt"] + 2)
    font_size_half_points = max(int(round(float(span["font_size_pt"]) * 2)), 12)
    xml = f"""
    <w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
         xmlns:v="urn:schemas-microsoft-com:vml"
         xmlns:o="urn:schemas-microsoft-com:office:office">
      <w:pPr>
        <w:spacing w:before="0" w:after="0"/>
      </w:pPr>
      <w:r>
        <w:pict>
          <v:shape id="{shape_id}" type="#_x0000_t202"
            style="position:absolute;margin-left:{left}pt;margin-top:{top}pt;width:{width}pt;height:{height}pt;z-index:251659264;mso-position-horizontal-relative:page;mso-position-vertical-relative:page"
            filled="f" stroked="f" o:allowincell="f">
            <v:textbox inset="0,0,0,0" style="mso-fit-shape-to-text:t">
              <w:txbxContent>
                <w:p>
                  <w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr>
                  <w:r>
                    <w:rPr>
                      <w:sz w:val="{font_size_half_points}"/>
                      <w:color w:val="000000"/>
                    </w:rPr>
                    <w:t xml:space="preserve">{text}</w:t>
                  </w:r>
                </w:p>
              </w:txbxContent>
            </v:textbox>
          </v:shape>
        </w:pict>
      </w:r>
    </w:p>
    """
    return parse_xml(xml)


def _pt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _append_body_element(document: Document, element: Any) -> None:
    body = document.element.body
    children = list(body)
    if children and children[-1].tag == qn("w:sectPr"):
        body.insert(len(children) - 1, element)
    else:
        body.append(element)


def _replace_known_fields_in_docx(
    docx_path: str | Path, profile: dict[str, Any]
) -> None:
    """Replace placeholder text and clean page numbers from a DOCX."""
    from docx import Document

    doc = Document(str(docx_path))
    _replace_known_fields(doc, profile)
    _remove_page_numbers_from_paragraphs(doc)
    doc.save(str(docx_path))


def _remove_page_numbers_from_paragraphs(doc: "Document") -> None:
    """Remove standalone page numbers (1-3 digit isolated lines) from paragraphs."""
    page_pattern = re.compile(r"^\s*\d{1,3}\s*$")
    for p in doc.paragraphs:
        text = p.text.strip()
        if page_pattern.match(text):
            # Clear the paragraph text
            for run in p.runs:
                run.text = ""
        # Also remove page number at end of paragraph
        for run in p.runs:
            if run.text and re.match(r"\s*\d{1,3}\s*$", run.text):
                run.text = re.sub(r"\s*\d{1,3}\s*$", "", run.text)


def _skip_toc_pages(pdf: fitz.Document, from_page: int) -> int:
    """Skip TOC pages after finding the format chapter heading."""
    # Check next few pages — if they're TOC (contain "........" dots), skip them
    for offset in range(MAX_TOC_PAGES):
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
