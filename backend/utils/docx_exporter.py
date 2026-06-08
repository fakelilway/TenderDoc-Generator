from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# Production typography for Chinese bid documents:
# body uses 宋体, headings use 黑体 (bold), Latin/digits use Times New Roman.
BODY_CJK_FONT = "SimSun"  # 宋体
HEADING_CJK_FONT = "SimHei"  # 黑体
FOOTER_CJK_FONT = "NSimSun"  # 新宋体
LATIN_FONT = "Times New Roman"
BODY_SIZE_PT = 12  # 小四
HEADING_SIZES_PT = {"Heading 1": 16, "Heading 2": 14, "Heading 3": 12}  # 三号/四号/小四
# 2-character first-line indent at the body font size.
FIRST_LINE_INDENT_PT = BODY_SIZE_PT * 2
ZHENGQI_PROFILE = "zhengqi"


# Headings whose title contains any of these keywords are routed to the
# commercial (商务标) volume when splitting a bid document into volumes.
COMMERCIAL_KEYWORDS = (
    "商务",
    "报价",
    "投标函",
    "投标报价",
    "开标一览",
    "资格审查",
    "资格证明",
    "营业执照",
    "财务",
    "信用",
    "承诺函",
    "声明函",
)


def markdown_to_docx(
    markdown_text: str,
    output_path: str | Path,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    cover: bool = False,
    toc: bool = False,
    header_text: str | None = None,
    page_numbers: bool = False,
    metadata: dict[str, str] | None = None,
    style_profile: str | None = None,
) -> str:
    """Render markdown into a styled DOCX file.

    The base behaviour (headings/paragraphs/lists/tables) is unchanged; the
    keyword-only arguments opt into the M58 formatting upgrades: a cover page,
    an auto-updating table of contents, running headers and page numbers.
    """
    if not markdown_text.strip():
        raise ValueError("markdown_text is empty")

    document = Document()
    _configure_styles(document, style_profile)

    if header_text or page_numbers:
        _configure_header_footer(document, header_text, page_numbers, style_profile)

    if cover:
        _add_cover_page(
            document,
            title or _extract_title(markdown_text) or "投标文件",
            subtitle,
            metadata,
            style_profile,
        )

    if toc:
        _add_table_of_contents(document)

    _render_markdown_body(document, markdown_text, style_profile)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    return str(path)


def _render_markdown_body(
    document: Document,
    markdown_text: str,
    style_profile: str | None,
) -> None:
    lines = markdown_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if not line:
            index += 1
            continue

        if _is_table_start(lines, index):
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            _add_table(document, table_lines, style_profile)
            continue

        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 3)
            title = line.lstrip("#").strip()
            if title:
                document.add_heading(title, level=level)
        elif line.startswith(("- ", "* ")):
            document.add_paragraph(line[2:].strip(), style="List Bullet")
        elif line[:3].isdigit() and line[3:5] in {". ", "、"}:
            document.add_paragraph(line[5:].strip(), style="List Number")
        else:
            paragraph = document.add_paragraph(line)
            # Production body paragraphs start with a 2-character indent.
            paragraph.paragraph_format.first_line_indent = Pt(
                _body_size_pt(style_profile) * 2
            )
        index += 1


def _body_size_pt(style_profile: str | None) -> float:
    return 14 if style_profile == ZHENGQI_PROFILE else BODY_SIZE_PT


def _set_fonts(style, cjk_font: str) -> None:
    """Set Latin + East-Asian fonts on a style (python-docx needs raw XML)."""
    style.font.name = LATIN_FONT
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), LATIN_FONT)
    rfonts.set(qn("w:hAnsi"), LATIN_FONT)
    rfonts.set(qn("w:cs"), LATIN_FONT)
    rfonts.set(qn("w:eastAsia"), cjk_font)


def _set_run_font(run, cjk_font: str, size_pt: float | None = None) -> None:
    run.font.name = LATIN_FONT
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), LATIN_FONT)
    rfonts.set(qn("w:hAnsi"), LATIN_FONT)
    rfonts.set(qn("w:cs"), LATIN_FONT)
    rfonts.set(qn("w:eastAsia"), cjk_font)


def _style_paragraph_runs(
    paragraph,
    cjk_font: str,
    size_pt: float | None = None,
) -> None:
    for run in paragraph.runs:
        _set_run_font(run, cjk_font, size_pt)


def _configure_styles(document: Document, style_profile: str | None) -> None:
    is_zhengqi = style_profile == ZHENGQI_PROFILE
    normal = document.styles["Normal"]
    _set_fonts(normal, BODY_CJK_FONT)
    normal.font.size = Pt(_body_size_pt(style_profile))
    normal.font.bold = False
    if is_zhengqi:
        normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        normal.paragraph_format.line_spacing = Pt(32)
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.space_after = Pt(3)
    else:
        normal.paragraph_format.line_spacing = 1.5

    heading_sizes = (
        {"Heading 1": 18, "Heading 2": 16, "Heading 3": 14}
        if is_zhengqi
        else HEADING_SIZES_PT
    )
    for style_name, size in heading_sizes.items():
        style = document.styles[style_name]
        _set_fonts(style, BODY_CJK_FONT if is_zhengqi else HEADING_CJK_FONT)
        style.font.bold = True
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)  # avoid the default blue heading colour
        style.paragraph_format.space_before = Pt(18 if is_zhengqi else 6)
        style.paragraph_format.space_after = Pt(12 if is_zhengqi else 6)
        if is_zhengqi and style_name == "Heading 1":
            style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif is_zhengqi:
            style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    for style_name in ("List Bullet", "List Number"):
        try:
            _set_fonts(document.styles[style_name], BODY_CJK_FONT)
            document.styles[style_name].font.size = Pt(_body_size_pt(style_profile))
        except KeyError:
            continue

    for section in document.sections:
        if is_zhengqi:
            section.top_margin = Cm(2.0)
            section.bottom_margin = Cm(1.8)
            section.left_margin = Cm(2.2)
            section.right_margin = Cm(1.8)
        else:
            section.top_margin = Pt(72)
            section.bottom_margin = Pt(72)
            section.left_margin = Pt(72)
            section.right_margin = Pt(72)


def _configure_header_footer(
    document: Document,
    header_text: str | None,
    page_numbers: bool,
    style_profile: str | None,
) -> None:
    is_zhengqi = style_profile == ZHENGQI_PROFILE
    for section in document.sections:
        if header_text:
            header_paragraph = section.header.paragraphs[0]
            header_paragraph.text = header_text
            header_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _style_paragraph_runs(header_paragraph, BODY_CJK_FONT, 12 if is_zhengqi else None)

        if page_numbers:
            footer_paragraph = section.footer.paragraphs[0]
            footer_paragraph.alignment = (
                WD_ALIGN_PARAGRAPH.RIGHT if is_zhengqi else WD_ALIGN_PARAGRAPH.CENTER
            )
            footer_paragraph.text = "第" if is_zhengqi else "第 "
            _style_paragraph_runs(
                footer_paragraph,
                FOOTER_CJK_FONT if is_zhengqi else BODY_CJK_FONT,
                10.5 if is_zhengqi else None,
            )
            _append_field(footer_paragraph, "PAGE")
            separator = "页/共" if is_zhengqi else " 页 / 共 "
            separator_run = footer_paragraph.add_run(separator)
            _set_run_font(
                separator_run,
                FOOTER_CJK_FONT if is_zhengqi else BODY_CJK_FONT,
                10.5 if is_zhengqi else None,
            )
            _append_field(footer_paragraph, "NUMPAGES")
            end_run = footer_paragraph.add_run("页" if is_zhengqi else " 页")
            _set_run_font(
                end_run,
                FOOTER_CJK_FONT if is_zhengqi else BODY_CJK_FONT,
                10.5 if is_zhengqi else None,
            )


def _add_cover_page(
    document: Document,
    title: str,
    subtitle: str | None,
    metadata: dict[str, str] | None,
    style_profile: str | None,
) -> None:
    is_zhengqi = style_profile == ZHENGQI_PROFILE
    for _ in range(4):
        document.add_paragraph()

    title_paragraph = document.add_paragraph()
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_paragraph.add_run(title)
    title_run.bold = True
    _set_run_font(title_run, BODY_CJK_FONT, 36 if is_zhengqi else 28)

    if subtitle:
        subtitle_paragraph = document.add_paragraph()
        subtitle_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle_run = subtitle_paragraph.add_run(subtitle)
        _set_run_font(subtitle_run, BODY_CJK_FONT, 16)

    if metadata:
        for _ in range(2):
            document.add_paragraph()
        for key, value in metadata.items():
            row = document.add_paragraph()
            row.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = row.add_run(f"{key}：{value}")
            _set_run_font(run, BODY_CJK_FONT, 14 if is_zhengqi else 12)

    document.add_page_break()


def _add_table_of_contents(document: Document) -> None:
    heading = document.add_heading("目录", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    paragraph = document.add_paragraph()
    run = paragraph.add_run()
    _append_field(
        run_or_paragraph=run,
        instruction='TOC \\o "1-3" \\h \\z \\u',
        placeholder="请在 Word 中右键“更新域”以生成目录。",
    )
    document.add_page_break()


def _append_field(
    run_or_paragraph,
    instruction: str,
    placeholder: str | None = None,
):
    """Append a Word field (e.g. PAGE/TOC) to a run or paragraph."""
    run = (
        run_or_paragraph.add_run()
        if hasattr(run_or_paragraph, "add_run")
        else run_or_paragraph
    )
    element = run._r

    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    element.append(begin)

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    element.append(instr)

    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    element.append(separate)

    if placeholder:
        text = OxmlElement("w:t")
        text.text = placeholder
        element.append(text)

    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    element.append(end)


def _extract_title(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return None


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    first = lines[index].strip()
    second = lines[index + 1].strip()
    return first.startswith("|") and second.startswith("|") and "---" in second


def _add_table(
    document: Document,
    table_lines: list[str],
    style_profile: str | None,
) -> None:
    is_zhengqi = style_profile == ZHENGQI_PROFILE
    rows = [_split_table_row(line) for line in table_lines]
    rows = [row for row in rows if row and not all(set(cell) <= {"-"} for cell in row)]
    if not rows:
        return

    column_count = max(len(row) for row in rows)
    table = document.add_table(rows=0, cols=column_count)
    table.style = "Table Grid"

    for row_values in rows:
        row = table.add_row()
        for index, value in enumerate(row_values):
            row.cells[index].text = value
            for paragraph in row.cells[index].paragraphs:
                _style_paragraph_runs(
                    paragraph,
                    BODY_CJK_FONT,
                    14 if is_zhengqi else BODY_SIZE_PT,
                )

    for cell in table.rows[0].cells:
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in paragraph.runs:
                run.bold = True


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def split_bid_markdown(markdown_text: str) -> dict[str, str]:
    """Split a single bid markdown into 技术标 / 商务标 volumes.

    Top-level sections (``##``) whose heading mentions commercial keywords are
    routed to the 商务标 volume; everything else stays in the 技术标 volume. The
    document title (``#``) is preserved as a prefix for both volumes. Returns a
    mapping with only the non-empty volumes.
    """
    lines = markdown_text.splitlines()
    doc_title = _extract_title(markdown_text)

    technical: list[str] = []
    commercial: list[str] = []
    current = technical

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            # Document level title; skip, it is re-added per volume.
            continue
        if stripped.startswith("## "):
            heading = stripped[3:]
            current = (
                commercial
                if any(keyword in heading for keyword in COMMERCIAL_KEYWORDS)
                else technical
            )
        current.append(line)

    volumes: dict[str, str] = {}
    for label, body in (("技术标", technical), ("商务标", commercial)):
        text = "\n".join(body).strip()
        if not text:
            continue
        prefix = f"# {doc_title}（{label}）\n\n" if doc_title else f"# {label}\n\n"
        volumes[label] = prefix + text
    return volumes


_SAFE_NAME_PATTERN = re.compile(r"[^\w.\-一-鿿]+", flags=re.UNICODE)


def build_export_filename(
    project_name: str,
    version: int = 1,
    kind: str | None = None,
    suffix: str = "docx",
) -> str:
    """Build a download filename containing the project name and version.

    Example: ``高层住宅项目_技术标_v2.docx``.
    """
    base = _SAFE_NAME_PATTERN.sub("_", (project_name or "投标文件").strip())
    base = base.strip("._") or "投标文件"
    parts = [base]
    if kind:
        parts.append(kind)
    parts.append(f"v{max(int(version), 1)}")
    return f"{'_'.join(parts)}.{suffix}"
