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

    This is intentionally not a markdown reconstruction path. Uses copy-then-prune
    (copy the source file, remove body children outside the format chapter) so the
    chapter keeps the tender's own Word XML AND its related parts — page
    headers/footers, embedded images, numbering — which a deepcopy into a fresh
    Document would drop. Merged cells, borders, underlines, alignment, spacing all
    survive.
    """
    source = Document(BytesIO(tender_docx_bytes))
    elements = list(source.element.body)
    start = _find_format_start(elements)
    if start is None:
        raise ValueError("未能在 DOCX 招标文件中定位“投标文件格式”章节，不能原样复制。")
    end = _find_format_end(elements, start)
    keep = set(range(start, end))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tender_docx_bytes)  # preserves headers/footers/images/parts

    target = Document(str(path))
    body = target.element.body
    for index, child in enumerate(list(body)):
        if child.tag == qn("w:sectPr"):
            continue  # keep the body section properties (and its header/footer refs)
        if index not in keep:
            body.remove(child)

    _replace_known_fields(target, profile or {})
    target.save(str(path))
    return str(path)


def _clear_document_body(document: Document) -> None:
    body = document.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def _is_toc_line(text: str) -> bool:
    """A table-of-contents entry: dot/leader run, or leaders followed by a page no."""
    return bool(
        re.search(r"[.．·…]{4,}", text)
        or re.search(r"[.．·…]{2,}\s*\d{1,4}\s*$", text)
    )


def _find_format_start(elements: list[Any]) -> int | None:
    """Locate the start of the format chapter body.

    The chapter heading appears multiple times — in the TOC, in 须知 references,
    and as the actual chapter title. Use the LAST non-TOC heading (the real
    chapter usually follows the TOC and the body references), mirroring the PDF
    path's "use the last match". Falls back to the first body-form marker.
    """
    format_headings: list[int] = []
    first_body_marker: int | None = None
    for index, element in enumerate(elements):
        text = _element_text(element)
        if not text:
            continue
        compact = re.sub(r"\s+", "", text)
        if FORMAT_CHAPTER_RE.search(compact) and not _is_toc_line(text):
            format_headings.append(index)
        if first_body_marker is None and any(
            marker in compact for marker in FORMAT_BODY_MARKERS
        ):
            first_body_marker = index
    if format_headings:
        return format_headings[-1]
    return first_body_marker


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
    duration = str(profile.get("工期") or profile.get("planned_duration") or "")
    quality = str(profile.get("质量") or profile.get("quality_standard") or "")
    safety = str(profile.get("安全") or profile.get("safety_target") or "")
    deadline = str(profile.get("投标有效期") or profile.get("投标截止时间") or profile.get("bid_deadline") or "")
    return {
        "（招标人）": tenderer,
        "（招标人名称）": tenderer,
        "受益人（招标人）名称": tenderer,
        "(招标人名称)": tenderer,
        "（招标项目名称）": project_name,
        "（项目名称）": project_name,
        "（投标人名称）": company,
        "（工期）": duration,
        "（计划工期）": duration,
        "（质量标准）": quality,
        "（质量要求）": quality,
        "（质量目标）": quality,
        "（安全目标）": safety,
        "（安全生产目标）": safety,
        "（投标有效期）": deadline,
        "（投标截止时间）": deadline,
        "（开标时间）": deadline,
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


def build_original_format_docx_from_pdf_editable(
    tender_pdf_bytes: bytes,
    output_path: str | Path,
    *,
    profile: dict[str, Any] | None = None,
) -> str:
    """Convert PDF format pages into an *editable* DOCX via pdf2docx, then fill fields.

    Unlike the image-based path, this reconstructs real Word paragraphs/tables so
    商务/报价 卷 can be 照抄 verbatim AND have known fields filled — no LLM. The
    reconstruction is layout-approximate (not pixel-perfect), so callers fall back
    to ``build_original_format_docx_from_pdf`` (整页截图) when this raises.

    The output has real text headings (投标文件（商务文件）…) and no PDF page
    markers, so it routes through the keyword-based DOCX volume split automatically.
    """
    import os
    import tempfile

    from pdf2docx import Converter

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        tmp_pdf.write(tender_pdf_bytes)
        pdf_path = tmp_pdf.name

    try:
        page_range = _find_format_page_range_in_pdf(pdf_path)
        if not page_range:
            raise ValueError("未能在 PDF 中定位“投标文件格式”章节")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        converter = Converter(pdf_path)
        try:
            # pdf2docx end is exclusive, matching our page_range convention.
            converter.convert(str(path), start=page_range[0], end=page_range[1])
        finally:
            converter.close()

        # Guard against an empty/failed reconstruction so the caller can fall back.
        doc = Document(str(path))
        has_text = any(p.text.strip() for p in doc.paragraphs)
        if not has_text and not doc.tables:
            raise ValueError("pdf2docx 转换结果为空，回退到整页截图路径。")

        _replace_known_fields(doc, profile or {})
        doc.save(str(path))
        return str(path)
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass


# Label keyword → profile keys to pre-fill the adjacent blank. Conservative
# allowlist; only single-value fields. Segmented blanks (成立时间 年/月/日) and
# anything not listed stay empty-but-editable.
_FILL_FIELD_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("投标人", ("company_name", "投标人", "公司名称")),
    ("单位性质", ("company_type", "单位性质", "公司类型")),
    ("址", ("registered_address", "注册地址", "地址")),  # 地 址 → '址：'
    ("名", ("legal_representative", "法定代表人", "姓名")),  # 姓 名 → '名：'
    ("法定代表", ("legal_representative", "法定代表人")),
    ("联系电话", ("contact_phone", "联系电话", "电话")),
    ("号码", ("contact_phone", "手机号码", "手机")),
)
# Labels whose blank is segmented or date-like → never auto-fill.
_FILL_SKIP_KEYWORDS = ("成立", "日期", "经营期限", "别", "龄", "务", "年", "月", "日")


def _detect_fill_underlines(page: Any) -> list[tuple[float, float, float]]:
    """Detect horizontal fill-in underlines on a PDF page → (x0, y, length)."""
    out: list[tuple[float, float, float]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return out
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":  # line segment
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 1.5 and abs(p2.x - p1.x) > 25:
                    x0 = min(p1.x, p2.x)
                    out.append((x0, p1.y, abs(p2.x - p1.x)))
    return out


def _fill_labels(page: Any) -> list[tuple[str, float, float, float]]:
    """Text spans ending in ：/: → (text, x0, y0, x1) used to anchor blanks."""
    labels: list[tuple[str, float, float, float]] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                if text.endswith("：") or text.endswith(":"):
                    x0, y0, x1, _ = span.get("bbox", (0, 0, 0, 0))
                    labels.append((text, x0, y0, x1))
    return labels


def _nearest_left_label(
    line_x: float, line_y: float, labels: list[tuple[str, float, float, float]]
) -> str | None:
    """Label immediately left of a blank on the same row."""
    best: str | None = None
    best_dist = 1e9
    for text, _x0, y0, x1 in labels:
        if y0 <= line_y + 2 and (line_y - y0) < 18 and x1 <= line_x + 30:
            dist = abs(line_y - y0) + (line_x - x1) * 0.01
            if dist < best_dist:
                best_dist = dist
                best = text
    return best


def _fill_value_for_label(label: str | None, profile: dict[str, Any]) -> str:
    if not label:
        return ""
    norm = label.rstrip("：:").replace(" ", "")
    if any(kw in norm for kw in _FILL_SKIP_KEYWORDS):
        return ""
    for keyword, keys in _FILL_FIELD_ALIASES:
        if keyword in norm:
            for key in keys:
                value = str(profile.get(key, "") or "").strip()
                if value:
                    return value
            return ""
    return ""


_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Songti.ttc",  # macOS
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",  # Linux Noto
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # WenQuanYi
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
)


def _find_cjk_font() -> str | None:
    import os

    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _bake_fill_values_on_page(page: Any, profile: dict[str, Any]) -> None:
    """Print known field values directly onto the PDF page at each fill-in
    underline, *before* rasterizing. The page then renders as a plain image —
    identical to the原件, viewer-independent (Pages/soffice/Word all show it) —
    with company info filled in. Unknown blanks stay empty for manual/新点 entry.

    VML text-box overlays were editable but suppressed page-image rendering in
    multi-section docs under LibreOffice/Pages; baking avoids that entirely.
    """
    values = [
        (x0, y_line, _fill_value_for_label(_nearest_left_label(x0, y_line, _fill_labels(page)), profile))
        for x0, y_line, _length in _detect_fill_underlines(page)
    ]
    if not any(v for _, _, v in values):
        return
    font = _find_cjk_font()
    for x0, y_line, value in values:
        if not value:
            continue
        try:
            kwargs = {"fontsize": 10.5}
            if font:
                kwargs["fontfile"] = font
                kwargs["fontname"] = "cjk"
            else:
                kwargs["fontname"] = "china-s"  # PyMuPDF built-in CJK fallback
            page.insert_text((x0 + 3, y_line - 2), value, **kwargs)
        except Exception:
            continue


def build_original_format_docx_from_pdf_with_fields(
    tender_pdf_bytes: bytes,
    output_path: str | Path,
    *,
    profile: dict[str, Any] | None = None,
) -> str:
    """Pixel-perfect format pages (full-page image) with knowledge-base values
    baked onto the fill-in blanks.

    Each PDF format page has its known field values printed onto the page (投标人/
    地址/法定代表人/电话…) at the detected fill-in underlines, then is rasterized and
    embedded. The result is identical to the原件 and renders in any viewer
    (Pages/LibreOffice/Word) with company info filled — unknown blanks stay empty
    for 新点/手工填写. Primary PDF format path; solves pdf2docx's underline
    misalignment without the VML overlay that broke multi-section image rendering
    under LibreOffice/Pages.
    """
    import os
    import tempfile

    import fitz
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt

    profile = profile or {}
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        tmp_pdf.write(tender_pdf_bytes)
        pdf_path = tmp_pdf.name

    try:
        page_range = _find_format_page_range_in_pdf(pdf_path)
        if not page_range:
            raise ValueError("未能在 PDF 中定位“投标文件格式”章节")

        pdf = fitz.open(pdf_path)
        try:
            docx = Document()
            _clear_document_body(docx)
            for index, page_num in enumerate(range(page_range[0], page_range[1])):
                page = pdf[page_num]
                section = docx.sections[0] if index == 0 else docx.add_section()
                _match_section_to_pdf_page(section, page)

                _bake_fill_values_on_page(page, profile)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(PDF_RENDER_DPI / 72, PDF_RENDER_DPI / 72),
                    alpha=False,
                )
                paragraph = docx.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                # Pin SINGLE line spacing as DIRECT formatting so it survives a
                # later _configure_styles (zhengqi sets Normal to EXACTLY 32pt,
                # which would clip the full-page image to 32pt → blank page).
                paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
                run = paragraph.add_run()
                run.add_picture(BytesIO(pix.tobytes("png")), width=section.page_width)

            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            docx.save(path)
        finally:
            pdf.close()
        return str(output_path)
    finally:
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
      <w:pPr><w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/></w:pPr>
      <w:r>
        <w:rPr><w:vanish/><w:sz w:val="2"/></w:rPr>
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
        <w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/>
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
