"""联合体/保证金留白 + 投标日期=今天 + 资料库图表注入 测试。"""

from __future__ import annotations

import datetime
from io import BytesIO

from docx import Document

from services import original_docx_format_service as o


def test_bond_left_blank_but_consortium_lead_name_fills() -> None:
    # 保证金 留白
    assert o._label_to_profile_key("投标保证金金额") == ""
    # 但"独立投标人或联合体牵头人名称"对单独投标人就该填公司名(不能误伤)
    assert o._label_to_profile_key("独立投标人或联合体牵头人名称") == "company_name"
    assert o._label_to_profile_key("投标人名称") == "company_name"


def test_inline_value_skips_bond() -> None:
    assert o._inline_value_for("投标保证金金额", {"company_name": "正奇"}) == ""


def test_consortium_agreement_section_blank() -> None:
    """联合体协议书"整章"留白:章节内的投标人名/日期都不自动填。"""
    doc = Document()
    doc.add_paragraph("联合体协议书")
    doc.add_paragraph("投标人：____")  # 在留白章节内 → 不填
    doc.add_paragraph("日期：    年   月   日")
    doc.add_paragraph("（三）下一章节")  # 编号章节 → 留白区结束
    doc.add_paragraph("投标人：____")  # 章节外 → 该填
    profile = {"company_name": "安徽正奇建设有限公司"}
    o._fill_inline_labeled_blanks(doc, profile)
    o._fill_bid_date_today(doc)
    assert "安徽正奇" not in doc.paragraphs[1].text  # 协议书内投标人 留白
    assert "2026" not in doc.paragraphs[2].text  # 协议书内日期 留白
    assert "安徽正奇" in doc.paragraphs[4].text  # 章节外投标人 正常填


def test_bid_date_today_split_runs() -> None:
    doc = Document()
    p = doc.add_paragraph()
    for t in ["日期：", "  ", "年", "  ", "月", "  ", "日"]:
        p.add_run(t)
    n = o._fill_bid_date_today(doc)
    d = datetime.date.today()
    assert n >= 1
    assert f"{d.year}年{d.month}月{d.day}日" in doc.paragraphs[0].text


def test_bid_date_today_single_run() -> None:
    doc = Document()
    doc.add_paragraph("投标日期：____年__月__日")
    o._fill_bid_date_today(doc)
    d = datetime.date.today()
    assert f"{d.year}年{d.month}月{d.day}日" in doc.paragraphs[0].text


def test_establish_date_not_touched_by_bid_date() -> None:
    doc = Document()
    doc.add_paragraph("成立日期：____年__月__日")
    assert o._fill_bid_date_today(doc) == 0


def test_inject_org_tables_copies_table(monkeypatch) -> None:
    # 造一个"源 docx"(含一个表格)
    src = Document()
    tbl = src.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "项目经理"
    buf = BytesIO()
    src.save(buf)
    src_bytes = buf.getvalue()

    from services import generation_service as g

    monkeypatch.setattr(
        g, "_fetch_org_source_docx",
        lambda kw: src_bytes if kw == "项目管理机构" else None,
    )

    target = Document()
    target.add_paragraph("项目管理机构")
    before = len(target.tables)
    inserted = g._inject_org_tables(target)
    assert inserted == 1
    assert len(target.tables) == before + 1
    assert "项目经理" in target.tables[-1].cell(0, 0).text


def test_strip_tender_page_numbers() -> None:
    from services.original_docx_format_service import _strip_tender_page_numbers
    doc = Document()
    doc.add_paragraph("正文内容")
    doc.add_paragraph("171")  # 招标原件页码
    doc.add_paragraph("第 5 页")
    n = _strip_tender_page_numbers(doc)
    texts = [p.text for p in doc.paragraphs]
    assert "171" not in texts and "第 5 页" not in texts
    assert "正文内容" in texts


def test_pm_resume_table_fill_scoped() -> None:
    from services.original_docx_format_service import _fill_pm_resume_table
    doc = Document()
    t = doc.add_table(rows=2, cols=4)
    t.cell(0, 0).text = "姓名"
    t.cell(0, 2).text = "职称"
    t.cell(1, 0).text = "拟在本标段工程担任职务"
    # 另一张表(无"拟在本标段")不应被填
    other = doc.add_table(rows=1, cols=2)
    other.cell(0, 0).text = "姓名"
    resume = {"姓名": "李刚", "职称": "工程师", "拟任职务": "项目经理"}
    _fill_pm_resume_table(doc, resume)
    assert t.cell(0, 1).text == "李刚"
    assert t.cell(1, 1).text == "项目经理"
    assert other.cell(0, 1).text.strip() == ""  # 非简历表不动


def test_org_table_anchor_skips_toc() -> None:
    from services import generation_service as g
    doc = Document()
    doc.add_paragraph("目录")
    doc.add_paragraph("五、项目管理机构")  # 目录条目
    doc.add_paragraph("投标函正文……（实质内容，退出目录）" + "x" * 30)
    real = doc.add_paragraph("五、项目管理机构")  # 正文真章节
    el = g._find_section_paragraph(doc, ("项目管理机构",))
    assert el is real._p  # 取正文章节,不取目录条目


def test_bond_mention_in_paragraph_does_not_blank_quality_duration() -> None:
    """投标函正文顺带提到'投标保证金'时,同段的质量/工期空仍要照填(修留白过宽回归)。"""
    from docx import Document as _D
    from services.original_docx_format_service import _fill_inline_labeled_blanks
    doc = _D()
    p = doc.add_paragraph()
    for t in ["3.质量标准：", " ", "\t", "；工期：", " ", "\t", "日历天。我方按时提交投标保证金。"]:
        p.add_run(t)
    _fill_inline_labeled_blanks(doc, {"质量": "合格", "工期": "90日历天"})
    txt = doc.paragraphs[0].text
    assert "合格" in txt and "90日历天" in txt
