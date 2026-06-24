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


def test_authorization_letter_fills_legal_rep_only() -> None:
    """授权委托书:本人___（姓名）系→法人名;代理人（姓名）留白;不误填随处的（姓名）。"""
    from docx import Document as _D
    from services.original_docx_format_service import _fill_authorization_letter
    doc = _D()
    p = doc.add_paragraph()
    for t in ["本人 ", "\t", "（姓名）系 ", "\t", "（投标人名称）的法定代表人，现委托 ", "\t", "（姓名）为我方代理人。"]:
        p.add_run(t)
    # 另一段普通"（姓名）"不该被填(无授权委托书语境)
    other = doc.add_paragraph("项目经理（姓名）：")
    _fill_authorization_letter(doc, {"legal_representative": "许明英"})
    t0 = doc.paragraphs[0].text
    assert "本人许明英（姓名）系" in t0  # 法人名填在第一个（姓名）前
    assert t0.count("许明英") == 1  # 代理人那个（姓名）没被填
    assert "许明英" not in other.text  # 无语境的（姓名）不动


def test_personnel_table_fills_pm_and_tech_rows() -> None:
    from docx import Document as _D
    from services.original_docx_format_service import _fill_personnel_table
    doc = _D()
    t = doc.add_table(rows=4, cols=5)
    for c, h in enumerate(["职务", "姓名", "职称", "证书名称", "证号"]):
        t.cell(0, c).text = h
        t.cell(1, c).text = h
    prof = {
        "project_manager_name": "江甜甜", "project_manager_cert": "皖234", "project_manager_title": "工程师",
        "tech_director_name": "李刚", "tech_director_cert": "皖134", "tech_director_title": "工程师",
    }
    _fill_personnel_table(doc, prof)
    assert [t.cell(2, c).text for c in (0, 1, 4)] == ["项目经理", "江甜甜", "皖234"]
    assert [t.cell(3, c).text for c in (0, 1, 4)] == ["项目技术负责人", "李刚", "皖134"]


def test_evidence_groups_drop_system_patent() -> None:
    from services.v2_generation_service import _EVIDENCE_GROUPS
    titles = [g[0] for g in _EVIDENCE_GROUPS]
    assert "管理体系认证证书" not in titles  # 体系删了
    assert "专利与工法证书" not in titles  # 专利工法删了
    # 基本情况表后只剩这4类
    basic = [g[0] for g in _EVIDENCE_GROUPS if g[3] == "基本情况表"]
    assert set(basic) == {"营业执照", "企业资质证书", "安全生产许可证", "基本账户开户许可证"}


def test_performance_table_fills_selected(monkeypatch) -> None:
    """投标人业绩情况表(业绩序号|项目名称|备注)按选中业绩填项目名,去重,保真。"""
    from docx import Document as _D
    d = _D(); t = d.add_table(rows=4, cols=3)
    for c, v in enumerate(["业绩序号", "项目名称（合同名称）", "备注"]):
        t.cell(0, c).text = v
    t.cell(1, 0).text = "1"; t.cell(2, 0).text = "2"; t.cell(3, 0).text = "……"
    prof = {"selected_performance": [
        {"name": "项目A"}, {"name": "项目A"}, {"name": "项目B"},
    ]}
    assert o._fill_performance_table(d, prof) == 2  # 去重后2个
    assert t.cell(1, 1).text == "项目A"
    assert t.cell(2, 1).text == "项目B"
    # 保真:首数据行已填则整表跳过
    d2 = _D(); t2 = d2.add_table(rows=2, cols=3)
    for c, v in enumerate(["业绩序号", "项目名称（合同名称）", "备注"]):
        t2.cell(0, c).text = v
    t2.cell(1, 1).text = "已填"
    assert o._fill_performance_table(d2, prof) == 0
    assert t2.cell(1, 1).text == "已填"


def test_performance_table_empty_when_no_selection() -> None:
    from docx import Document as _D
    d = _D(); t = d.add_table(rows=2, cols=3)
    for c, v in enumerate(["业绩序号", "项目名称", "备注"]):
        t.cell(0, c).text = v
    assert o._fill_performance_table(d, {}) == 0


def test_signature_bidder_line_both_cases() -> None:
    """签名块投标人行:存在则填空补上(不重复加)、缺失则重建。"""
    from docx import Document as _D
    from services.original_docx_format_service import (
        _fill_inline_labeled_blanks, _fill_signature_bidder_line,
    )
    prof = {"company_name": "安徽正奇建设有限公司"}
    # A 行存在但空 → 填空填上,重建加0
    a = _D(); p = a.add_paragraph()
    for t in ["投 标 人：", " ", "\t", "（盖单位章）"]:
        p.add_run(t)
    a.add_paragraph().add_run("法定代表人： \t（签字或盖章）")
    _fill_inline_labeled_blanks(a, prof)
    assert _fill_signature_bidder_line(a, prof) == 0
    assert "安徽正奇建设有限公司" in a.paragraphs[0].text
    # B 行缺失 → 重建补1行,在法定代表人前
    b = _D()
    b.add_paragraph().add_run("（其他补充说明）。")
    b.add_paragraph()
    b.add_paragraph().add_run("法定代表人： \t（签字或盖章）")
    assert _fill_signature_bidder_line(b, prof) == 1
    texts = [x.text for x in b.paragraphs]
    bidder_i = next(i for i, t in enumerate(texts) if "投 标 人" in t)
    rep_i = next(i for i, t in enumerate(texts) if "法定代表人" in t)
    assert bidder_i < rep_i and "安徽正奇建设有限公司" in texts[bidder_i]
    # 联合体协议书区不补
    c = _D()
    c.add_paragraph().add_run("联合体协议书")
    c.add_paragraph().add_run("法定代表人： \t（签字或盖章）")
    assert _fill_signature_bidder_line(c, prof) == 0


def test_legal_rep_columns_rebuild() -> None:
    """福昕切断的 性别/职务 右列重建(姓名：X性→补性别;年龄：X职→补职务)。"""
    from docx import Document as _D
    from services.original_docx_format_service import _fill_legal_rep_columns
    prof = {"法人性别": "女", "法人职务": "总经理"}
    d = _D()
    p1 = d.add_paragraph()
    for t in ["姓", " ", "名", "：", " ", "许明英", "性"]:
        p1.add_run(t)
    p2 = d.add_paragraph()
    for t in ["年", " ", "龄", "：", " ", "50", "职"]:
        p2.add_run(t)
    assert _fill_legal_rep_columns(d, prof) == 2
    assert "性别：女" in d.paragraphs[0].text and "许明英" in d.paragraphs[0].text
    assert not d.paragraphs[0].text.rstrip().endswith("性")  # 漏出的'性'已去掉
    assert "职务：总经理" in d.paragraphs[1].text
    assert not d.paragraphs[1].text.rstrip().endswith("职")
    # 正常姓名不动
    d2 = _D(); d2.add_paragraph().add_run("姓 名： 张三")
    assert _fill_legal_rep_columns(d2, prof) == 0
