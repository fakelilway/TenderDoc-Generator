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
# A real next-chapter heading sits at the very start of a page (optionally after
# the page number), e.g. "106第八章评标办法". Anchoring here avoids treating a
# mid-sentence cross-reference ("…招标文件第二章…的要求") as a chapter boundary.
_NEXT_CHAPTER_HEAD_RE = re.compile(r"^\d{0,5}第[一二三四五六七八九十百\d]+章")
# Start of the 技术文件/报价文件 卷 inside the "投标文件格式" 章, e.g.
# "（标段名称）施工招标投标文件（技术文件）". The 商务卷 copy ends here.
_OTHER_VOLUME_START_RE = re.compile(r"投标文件\s*[（(]\s*(?:技术|报价|经济)")
# 技术卷附表区起始:页首(可带页码)就是"附表一 …"的那页才算起点,避免命中正文里
# 引用"附表一"的页或附表目录页(注:不可套 _skip_toc_pages——它会把稀疏附表误判成 TOC、丢表)。
_APPENDIX_START_RE = re.compile(r"^\d{0,5}附表一")
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
    _strip_seal_images(target)  # 清招标原件带进来的招标人/代理红章(投标人章须人工手盖)
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

        _drop_spurious_stream_tables(doc)  # 删 pdf2docx 把填空行误判出的假表
        _replace_known_fields(doc, profile or {})
        _fill_known_table_cells(doc, profile or {})
        _fill_personnel_table(doc, profile or {})  # 项目管理机构人员表填项目经理行
        _strip_seal_images(doc)  # 清招标原件带进来的招标人/代理红章
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


# ── 可编辑路径(pdf2docx)的表格自动填 ──────────────────────────────────
# 整页截图烧录只认下划线;可编辑路径产出真实 Word 表格(如投标人基本情况表),
# 这里按"标签单元格 → 同行右侧第一个空值格"填入公司档案。用**精确整标签**匹配
# (不用 _FILL_FIELD_ALIASES 的单字短键),避免技术负责人行的"姓名"被误填成法定
# 代表人。只写空格、不覆盖、不改表结构 → 保真。
_TABLE_FILL_LABELS: tuple[tuple[str, str], ...] = (
    ("投标人名称", "company_name"),
    ("投标人", "company_name"),
    ("注册地址", "registered_address"),
    ("单位性质", "company_type"),
    ("统一社会信用代码", "credit_code"),
    ("信用代码", "credit_code"),
    ("注册资本", "registered_capital"),
    ("企业资质等级", "qualification_grade"),
    ("资质等级", "qualification_grade"),
    ("法定代表人", "legal_representative"),
    ("项目经理", "project_manager_name"),
    ("注册建造师", "project_manager_name"),
    ("安全生产许可证", "safety_license_no"),
    ("开户银行", "bank_name"),
    ("银行账号", "bank_account"),
    ("联系人", "contact_person"),
    ("经营范围", "business_scope"),
    ("成立时间", "establish_date"),
    ("成立日期", "establish_date"),
)
# 这些是"另一个人/无对应档案字段"的标签,绝不当作待填项。
_TABLE_FILL_SKIP = (
    "技术负责人", "项目总工", "技术职称", "员工总人数",
    "邮政编码", "电子邮件", "传真",
)
# 子标签:行标签与值格之间的小标题(如 法定代表人 | 姓名 | [值]),右扫时跳过去找值格。
_TABLE_SUBLABELS = frozenset(
    {"姓名", "职称", "级别", "证号", "证书名称", "专业", "养老保险", "电话"}
)
_TABLE_BLANK_RE = re.compile(r"^[\s_＿]*$")

# 宽泛"主体"键:标签里**含**它 ≠ 就该填它的名字。"投标人响应资质 / 项目经理身份证
# 号码 / …荣誉 / …业绩"含主体词但问的是别的字段——绝不能拿公司名/项目经理名去填(实测
# 122 商务卷正栽在这:项目经理身份证号被填成"江舟"、牵头人信用代码被填成公司名)。仅当
# 标签是"要名字"(键本身,或键+名称/姓名等名字尾巴)时才填,否则留空待人工。
_BROAD_ENTITY_KEYS = frozenset({"投标人", "项目经理", "注册建造师"})
_NAME_TAILS = frozenset({"名称", "姓名", "名", "全称", "单位名称"})
# 判定"是否只剩名字尾巴"前,先剥掉这些主体周围的修饰词/装饰。
_ENTITY_MODIFIERS = (
    "独立", "或联合体", "联合体", "牵头人", "或", "单位", "本",
    "盖章", "公章", "签字", "（", "）", "(", ")",
)


def _table_label_value(label: str, profile: dict[str, Any]) -> str:
    norm = (
        label.replace(" ", "").replace("　", "").replace("：", "").replace(":", "").strip()
    )
    if not norm or any(skip in norm for skip in _TABLE_FILL_SKIP):
        return ""
    # 取所有命中键里**最长(最具体)**的:让"统一社会信用代码"胜过宽泛的"投标人",
    # 修复原来 first-in-list-order 误配(如"…牵头人统一社会信用代码"被当成投标人名称)。
    matches = [(key, pkey) for key, pkey in _TABLE_FILL_LABELS if key in norm]
    if not matches:
        return ""
    key, profile_key = max(matches, key=lambda kp: len(kp[0]))
    # 宽泛主体键防误填:只有"要名字"的标签才填名字。
    if key in _BROAD_ENTITY_KEYS:
        remainder = norm.replace(key, "", 1)
        for modifier in _ENTITY_MODIFIERS:
            remainder = remainder.replace(modifier, "")
        if remainder and remainder not in _NAME_TAILS:
            return ""
    return str(profile.get(profile_key, "") or "").strip()


def _set_cell_value(cell: Any, value: str) -> None:
    """Write a value into a table cell with a form-fitting font (宋体五号).

    新建空格默认会继承偏大的字号,在窄列(职务/证号 等)里被裁成"项目经""皖";
    显式设宋体 10.5pt 让 4 字职务/长证号能容下(过长则自动换行)。
    """
    from docx.shared import Pt

    paragraph = cell.paragraphs[0]
    runs = paragraph.runs
    if runs:
        run = runs[0]
        run.text = value
        for extra in runs[1:]:
            extra.text = ""
    else:
        run = paragraph.add_run(value)
    run.font.name = "Times New Roman"
    run.font.size = Pt(10.5)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(attr), "Times New Roman")
    rfonts.set(qn("w:eastAsia"), "SimSun")
    # 允许长串(如 17 位证号)在窄列里折行,而不是溢出被裁成"皖"
    from docx.oxml import OxmlElement

    p_pr = paragraph._p.get_or_add_pPr()
    if p_pr.find(qn("w:wordWrap")) is None:
        word_wrap = OxmlElement("w:wordWrap")
        word_wrap.set(qn("w:val"), "0")
        p_pr.append(word_wrap)


def _row_label_at(
    cells: Any, i: int, profile: dict[str, Any]
) -> tuple[str, int]:
    """从 cells[i] 起识别标签,支持被逐字拆进相邻短格的"碎标签"。

    中文公文表常把"投标人："逐字对齐成 `投|标|人：` 三格,单格匹配不到。
    这里把从 i 起连续的短格(≤3 字、非空)拼起来再匹配已知标签;一旦命中即返回
    ``(value, label_end_index)``(label_end 为标签占用的最后一格下标)。未命中返回
    ``("", i)``。只匹配 ``_TABLE_FILL_LABELS`` 里已有的标签,故不会凭空造出新标签。
    """
    text = cells[i].text.strip()
    value = _table_label_value(text, profile)
    if value:
        return value, i
    # 碎标签重组:仅拼接 ≤3 字的相邻短格(标签碎片如 投/标/人:),遇到值格/长文本即停。
    joined = text
    for k in range(i + 1, min(i + 4, len(cells))):
        if cells[k]._tc is cells[i]._tc:
            break  # 合并单元格,不算相邻碎片
        nxt = cells[k].text.strip()
        if not nxt or len(nxt) > 3:
            break
        joined += nxt
        v = _table_label_value(joined, profile)
        if v:
            return v, k
    return "", i


def _fill_known_table_cells(document: Any, profile: dict[str, Any]) -> int:
    """基本情况表式网格自动填:标签格 → 同行右侧第一个空值格。

    只写空格、绝不覆盖、不改表结构(保真);未知标签和第二个人的子标签保持空白。
    支持标签被逐字拆进相邻格的"碎标签"(见 _row_label_at)。返回填入的格数。
    """
    if not any(profile.get(key) for _, key in _TABLE_FILL_LABELS):
        return 0
    filled = 0
    for table in document.tables:
        for row in table.rows:
            cells = row.cells
            n = len(cells)
            i = 0
            while i < n:
                value, label_end = _row_label_at(cells, i, profile)
                if not value:
                    i += 1
                    continue
                for j in range(label_end + 1, n):
                    target = cells[j]
                    if target._tc is cells[i]._tc:
                        continue  # 同一个合并单元格(含碎标签所在格)
                    text = target.text.strip()
                    if text and _table_label_value(text, profile):
                        break  # 右邻又是个已知标签,本标签不填
                    if text in _TABLE_SUBLABELS:
                        continue  # 子标签(姓名/职称等),跳过去找它后面的值格
                    if _TABLE_BLANK_RE.match(text):
                        _set_cell_value(target, value)
                        filled += 1
                    break
                i = label_end + 1
    return filled


def _fill_personnel_table(document: Any, profile: dict[str, Any]) -> bool:
    """填"项目管理机构人员组成表"的项目经理行(职务/姓名/证号),从公司档案取。

    这是列表头驱动的多列表(职务|姓名|职称|证书名称|级别|证号|专业|养老保险|备注),
    与"标签格→右邻"不同。只填项目经理这一行、只填空格、不改表结构;其余人员留给人工
    或后续按知识库补。返回是否填了。
    """
    pm_name = str(profile.get("project_manager_name") or "").strip()
    if not pm_name:
        return False
    pm_cert = str(profile.get("project_manager_cert") or "").strip()

    for table in document.tables:
        try:
            rows = table.rows
            n_cols = len(table.columns)
            if len(rows) < 2 or n_cols < 3:
                continue

            def header(col: int, _rows=rows, _table=table) -> str:
                return " ".join(
                    _table.cell(r, col).text.strip() for r in range(min(2, len(_rows)))
                )

            headers = [header(c) for c in range(n_cols)]
            col_role = next((c for c, h in enumerate(headers) if "职务" in h), None)
            col_name = next((c for c, h in enumerate(headers) if "姓名" in h), None)
            col_cert = next(
                (c for c, h in enumerate(headers) if "证号" in h or "证书号" in h), None
            )
            if col_role is None or col_name is None:
                continue
            # 必须是"人员组成"表(含证书/资格证明列),别误填别的两列表
            if not any(("证书" in h or "资格证明" in h or "证号" in h) for h in headers):
                continue
            # 执业资格证明跨行、子列在第2行 → 表头占2行,数据从第3行起
            two_row_header = any(
                ("证书名称" in headers[c] or "级别" in headers[c] or "证号" in headers[c])
                for c in range(n_cols)
            )
            data_r = 2 if two_row_header else 1
            if data_r >= len(rows):
                continue

            name_cell = table.cell(data_r, col_name)
            if not _TABLE_BLANK_RE.match(name_cell.text.strip()):
                continue  # 第一行已有人,留给人工
            _set_cell_value(name_cell, pm_name)
            role_cell = table.cell(data_r, col_role)
            if _TABLE_BLANK_RE.match(role_cell.text.strip()):
                _set_cell_value(role_cell, "项目经理")
            if col_cert is not None and pm_cert:
                cert_cell = table.cell(data_r, col_cert)
                if _TABLE_BLANK_RE.match(cert_cell.text.strip()):
                    _set_cell_value(cert_cell, pm_cert)
            return True
        except Exception:
            continue
    return False


def _image_is_seal(blob: bytes) -> bool:
    """True if the image is a red ink seal (公章/印章).

    印章=红印泥,整图红像素占比高(实测招标人/代理公章 22%~30%);证件扫描、附表
    线框图、页面截图近 0%(黑字白底,即便角上有小红章也 <2%)。阈值 5% 干净区分。
    """
    from io import BytesIO

    try:
        from PIL import Image

        im = Image.open(BytesIO(blob)).convert("RGBA")
    except Exception:
        return False
    w, h = im.size
    if w * h == 0:
        return False
    if w * h > 14400:  # 大图抽样提速,不影响占比估计
        im = im.resize((min(w, 120), min(h, 120)))
    pixels = list(im.getdata())
    red = sum(
        1
        for r, g, b, a in pixels
        if a > 40 and r > 110 and r - g > 40 and r - b > 40
    )
    return bool(pixels) and red / len(pixels) > 0.05


def _strip_seal_images(document: Any) -> int:
    """删除从招标原件复制进来的红色印章图(招标人/代理公章)。

    投标文件不该带招标人/代理的章,投标人自己的章必须人工手盖 → 任何自动出现的印章
    都要清掉。在**格式章构建阶段**调用(此时还没追加资格证明附录,故绝不会误删证件
    扫描件)。判据见 :func:`_image_is_seal`(整图红占比)。返回删除的图章引用数。
    """
    seal_rids = set()
    for rid, part in document.part.related_parts.items():
        if "image" not in (getattr(part, "content_type", "") or ""):
            continue
        blob = getattr(part, "blob", b"")
        if blob and _image_is_seal(blob):
            seal_rids.add(rid)
    if not seal_rids:
        return 0

    removed = 0
    blip_tag, embed_attr = qn("a:blip"), qn("r:embed")
    try:
        vml_tag, vml_id = qn("v:imagedata"), qn("r:id")
    except Exception:  # pragma: no cover - 'v' 命名空间缺失时退化为只处理 drawing
        vml_tag = vml_id = None
    for container in (qn("w:drawing"), qn("w:pict")):
        for element in list(document.element.iter(container)):
            rid = next(
                (b.get(embed_attr) for b in element.iter(blip_tag)), None
            )
            if rid is None and vml_tag is not None:
                rid = next(
                    (img.get(vml_id) for img in element.iter(vml_tag)), None
                )
            if rid in seal_rids:
                parent = element.getparent()
                if parent is not None:
                    parent.remove(element)
                    removed += 1
    return removed


def _table_has_real_borders(table: Any) -> bool:
    """True if any cell declares a real (non-nil) border.

    pdf2docx gives真实表格(基本情况表等)逐格 w:tcBorders=single;而把填空行误判出的
    "假表"边框为空。据此区分真表 vs 流式误判表。
    """
    sides = ("w:top", "w:bottom", "w:start", "w:end", "w:left", "w:right")
    for row in table.rows:
        for cell in row.cells:
            tc_pr = cell._tc.tcPr
            if tc_pr is None:
                continue
            borders = tc_pr.find(qn("w:tcBorders"))
            if borders is None:
                continue
            for side in sides:
                element = borders.find(qn(side))
                if element is not None and (
                    element.get(qn("w:val")) or ""
                ).lower() not in ("", "nil", "none"):
                    return True
    return False


def _drop_spurious_stream_tables(document: Any) -> int:
    """Flatten pdf2docx 的"假表"回普通段落。

    pdf2docx 偶尔把"标签+一段宽下划线空白"的填空行误判成 2 格无线表。这类
    (逻辑格数≤2 且 无真边框)还原成段落;真网格表(有边框,如基本情况表/图说明)保留。
    返回还原的表数。
    """
    from docx.oxml import OxmlElement

    dropped = 0
    for table in list(document.tables):
        if len(table.rows) * len(table.columns) > 2:
            continue
        if _table_has_real_borders(table):
            continue
        text = " ".join(
            cell.text.strip()
            for row in table.rows
            for cell in row.cells
            if cell.text.strip()
        )
        tbl = table._tbl
        paragraph = OxmlElement("w:p")
        if text:
            run = OxmlElement("w:r")
            node = OxmlElement("w:t")
            node.set(qn("xml:space"), "preserve")
            node.text = text
            run.append(node)
            paragraph.append(run)
        tbl.addprevious(paragraph)
        tbl.getparent().remove(tbl)
        dropped += 1
    return dropped


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

        # Find the end: the next real chapter heading, OR the start of the
        # 技术文件/报价文件 卷 (the format chapter packs all three volumes; the
        # 商务卷 copy must stop where 技术/报价 begins — those are生成/外部, not copied).
        format_end = doc.page_count
        for page_num in range(format_start + 1, doc.page_count):
            compact = page_compacts[page_num]
            if _looks_like_next_chapter_page(compact) or _looks_like_other_volume_start(
                compact
            ):
                format_end = page_num
                break

        return (format_start, max(format_start + 1, format_end))
    finally:
        doc.close()


def _find_appendix_page_range_in_pdf(pdf_path: str) -> tuple[int, int] | None:
    """定位技术卷附表区(附表一…)的零基、右开页范围。

    附表模板落在"投标文件格式"章的技术文件段;从"附表一"起,到报价文件卷起始或下一章止。
    商务范围(_find_format_page_range_in_pdf)已在技术卷起始处收尾、不含附表,故附表单独定位。
    """
    import fitz

    doc = fitz.open(pdf_path)
    try:
        compacts = [
            re.sub(r"\s+", "", doc[i].get_text()) for i in range(doc.page_count)
        ]
        start = next(
            (i for i, c in enumerate(compacts) if _APPENDIX_START_RE.search(c)), None
        )
        if start is None:
            return None
        end = doc.page_count
        for i in range(start + 1, doc.page_count):
            if _looks_like_other_volume_start(compacts[i]) or _looks_like_next_chapter_page(
                compacts[i]
            ):
                end = i
                break
        return (start, max(start + 1, end))
    finally:
        doc.close()


def _looks_like_next_chapter_page(compact_text: str) -> bool:
    """Detect a NEW chapter heading at the START of a PDF page.

    A real chapter heading sits at the very start of the page (optionally after a
    leading page number), e.g. "106第八章评标办法". A "第X章" embedded mid-sentence
    is a cross-reference (e.g. "投标人应根据招标文件第二章…的要求") and must NOT end
    the format chapter — searching the whole page head for it falsely cut the
    chapter and dropped later 商务 form pages (实测招标#122：p105 的
    "…招标文件第二章…" 把资格审查后半 + 八、其他资料切掉)。
    """
    head = compact_text[:40]
    if not _NEXT_CHAPTER_HEAD_RE.match(head):
        return False
    return not FORMAT_CHAPTER_RE.search(head)


def _looks_like_other_volume_start(compact_text: str) -> bool:
    """Detect the start of the 技术文件/报价文件 卷 within the format chapter.

    The "投标文件格式" 章 packs all three volumes; these volume headings (not
    "第X章") mark where the 商务卷 ends — 技术卷由 LLM 生成、报价卷外部,不照抄。
    """
    return bool(_OTHER_VOLUME_START_RE.search(compact_text[:60]))


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
