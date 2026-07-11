"""员工反馈第2/3/6条(面子工程)的格式修复测试。

2: 填空时冒号后的长空格一并吃掉,值紧贴冒号,不再被空格推开。
3: 表格行禁止跨页拆分(cantSplit) + 标题与下文同页(keepNext)。
6: 章(二级标题)另起一页,不再与上一章续写。
"""

from docx import Document
from docx.oxml.ns import qn


def _page_break_count(document) -> int:
    return len([
        br for br in document.element.body.iter(qn("w:br"))
        if br.get(qn("w:type")) == "page"
    ])


# ── 第2条:填空前后空格 ────────────────────────────────────────────────


def test_inline_fill_eats_long_leading_spaces() -> None:
    """冒号后连排长空格视为书写槽,填值后值紧贴冒号,长空格消失。"""
    from services.original_docx_format_service import _fill_inline_labeled_blanks

    doc = Document()
    p = doc.add_paragraph()
    p.add_run("工程质量：　　　　　；安全目标：无事故")  # 5个全角空格槽
    _fill_inline_labeled_blanks(doc, {"质量": "优良"})
    assert doc.paragraphs[0].text == "工程质量：优良；安全目标：无事故"


def test_inline_fill_eats_spaces_before_underscore_slot() -> None:
    """空格+下划线混合槽:整段(空格含)被值替换。"""
    from services.original_docx_format_service import _fill_inline_labeled_blanks

    doc = Document()
    p = doc.add_paragraph()
    p.add_run("工程质量：  ＿＿＿＿；")
    _fill_inline_labeled_blanks(doc, {"质量": "合格"})
    assert doc.paragraphs[0].text == "工程质量：合格；"


def test_inline_fill_keeps_single_space_gap() -> None:
    """单个空格是正常间隔,保留(不破坏原排版习惯)。"""
    from services.original_docx_format_service import _fill_inline_labeled_blanks

    doc = Document()
    p = doc.add_paragraph()
    p.add_run("工程质量： （按招标要求）")
    _fill_inline_labeled_blanks(doc, {"质量": "合格"})
    assert doc.paragraphs[0].text == "工程质量： 合格（按招标要求）"


# ── 第6条:章另起一页 ──────────────────────────────────────────────────


def test_chapter_headings_start_new_page() -> None:
    """二级标题(章)前自动分页;开头第一块内容前不分(防空白页)。"""
    from utils.docx_exporter import _render_markdown_body

    doc = Document()
    md = "# 某项目 技术文件\n\n## 第一章 总体布置\n正文A\n\n## 第二章 施工方案\n正文B\n"
    _render_markdown_body(doc, md, "zhengqi")
    # 卷标题后第一章前 1 次 + 第二章前 1 次 = 2
    assert _page_break_count(doc) == 2


def test_first_chapter_at_doc_start_no_break() -> None:
    """文档一开头就是章标题 → 不插分页(当前页还没内容)。"""
    from utils.docx_exporter import _render_markdown_body

    doc = Document()
    _render_markdown_body(doc, "## 第一章\n正文\n", "zhengqi")
    assert _page_break_count(doc) == 0


def test_explicit_pagebreak_not_doubled() -> None:
    """显式分页标记后紧跟章标题 → 不再叠加第二个分页。"""
    from utils.docx_exporter import _render_markdown_body

    doc = Document()
    md = "正文…\n\n<!-- tdg:pagebreak -->\n\n## 新章\n内容\n"
    _render_markdown_body(doc, md, "zhengqi")
    assert _page_break_count(doc) == 1  # 只有显式那一个


def test_third_level_heading_no_break() -> None:
    """三级标题(节)不分页,只有章分页。"""
    from utils.docx_exporter import _render_markdown_body

    doc = Document()
    md = "## 第一章\n正文\n\n### 1.1 小节\n内容\n\n### 1.2 小节\n内容\n"
    _render_markdown_body(doc, md, "zhengqi")
    assert _page_break_count(doc) == 0


# ── 第3条:防内容被拆页 ────────────────────────────────────────────────


def test_heading_styles_keep_with_next() -> None:
    """标题样式带"与下文同页",标题不孤悬页底。"""
    from utils.docx_exporter import _configure_styles

    doc = Document()
    _configure_styles(doc, "zhengqi")
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        assert doc.styles[name].paragraph_format.keep_with_next is True


def test_table_rows_cant_split() -> None:
    """heal_table_row_integrity 给所有行加 cantSplit;幂等(第二次跑=0)。"""
    from services.docx_format_doctor import heal_table_row_integrity

    doc = Document()
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "姓名"
    fixed = heal_table_row_integrity(doc)
    assert fixed == 3
    for row in t.rows:
        trPr = row._tr.find(qn("w:trPr"))
        assert trPr is not None and trPr.find(qn("w:cantSplit")) is not None
    assert heal_table_row_integrity(doc) == 0  # 幂等


def test_assembled_doctor_includes_row_integrity() -> None:
    """成品级体检注册了表格行防拆页。"""
    from services.docx_format_doctor import run_format_doctor_assembled

    doc = Document()
    doc.add_table(rows=2, cols=2)
    report = run_format_doctor_assembled(doc)
    assert report.get("table_row_integrity") == 2
