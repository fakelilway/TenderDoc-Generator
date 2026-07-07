"""格式体检(docx_format_doctor)测试:治下划线断线,铁律=只改格式一字不改。

病例全部来自真实文件(巢湖商务卷 v7)的实测结构。
"""

from docx import Document

from services.docx_format_doctor import heal_underline_slots, run_format_doctor


def _mk_para(doc, runs):
    """runs: [(text, underlined)]"""
    p = doc.add_paragraph()
    for text, u in runs:
        r = p.add_run(text)
        if u:
            r.font.underline = True
    return p


def test_sandwich_value_gets_underlined() -> None:
    """投标函项目名:带线空白+无线值+带线空白 → 值上线,整条线连续。"""
    doc = Document()
    p = _mk_para(doc, [
        ("我方已仔细研究", False), (" ", True), ("\t", True),
        ("巢湖市 2026 年农村公路养护工程（栏杆集镇周岗路等 8 条路）", False),
        (" ", True), ("\t", True), ("标段招标文件的全部内容，", False),
    ])
    before = p.text
    n = heal_underline_slots(doc)
    assert n == 1
    assert p.runs[3].font.underline  # 项目名上线
    assert not p.runs[0].font.underline  # 槽外正文不动
    assert not p.runs[6].font.underline
    assert p.text == before  # 一字不改


def test_short_labels_year_month_day_untouched() -> None:
    """日期槽"年/月/日"被线夹着是招标原样,绝不误加线。"""
    doc = Document()
    p = _mk_para(doc, [
        ("日期：", False), (" ", True), ("\t", True), ("年", False),
        (" ", True), ("\t", True), ("月", False),
        (" ", True), ("\t", True), ("日", False),
    ])
    heal_underline_slots(doc)
    for r in p.runs:
        if r.text in ("年", "月", "日"):
            assert not r.font.underline


def test_whitelist_splits_value_from_tail() -> None:
    """抬头"招标人名称："/委托书"公司名的法定代表人":拆 run 只给值上线,尾巴不动。"""
    doc = Document()
    p1 = _mk_para(doc, [(" ", True), ("\t", True), ("巢湖市栏杆集镇人民政府：", False)])
    p2 = _mk_para(doc, [
        ("系", False), (" ", True), ("\t", True),
        ("安徽正奇建设有限公司的法定代表人，现委托", False), (" ", True), ("\t", True),
    ])
    t1, t2 = p1.text, p2.text
    profile = {"招标人": "巢湖市栏杆集镇人民政府", "company_name": "安徽正奇建设有限公司"}
    n = heal_underline_slots(doc, profile)
    assert n == 2
    assert p1.runs[2].font.underline and p1.runs[2].text == "巢湖市栏杆集镇人民政府"
    assert not p1.runs[3].font.underline and p1.runs[3].text == "："
    assert p2.runs[3].font.underline and p2.runs[3].text == "安徽正奇建设有限公司"
    assert not p2.runs[4].font.underline  # "的法定代表人，现委托" 不上线
    assert p1.text == t1 and p2.text == t2  # 一字不改


def test_sentence_text_sandwiched_not_underlined_without_whitelist() -> None:
    """值+原文连排(带句读)且 profile 没给值 → 夹心兜底不动它(宁漏勿错)。"""
    doc = Document()
    p = _mk_para(doc, [
        (" ", True), ("\t", True),
        ("安徽正奇建设有限公司的法定代表人，现委托", False), (" ", True),
    ])
    heal_underline_slots(doc)  # 无 profile
    assert not p.runs[2].font.underline


def test_hint_parenthetical_untouched() -> None:
    """（其他补充说明）等原文提示语不上线。"""
    doc = Document()
    p = _mk_para(doc, [(" ", True), ("\t", True), ("（其他补充说明）。", False), (" ", True)])
    heal_underline_slots(doc)
    assert not p.runs[2].font.underline


def test_orphan_split_labels_rejoined() -> None:
    """孤字归位(巢湖v7身份证明实测病例):性/职 粘在带线值后 + 下文"别：/务："段 → 拼回。"""
    import re

    doc = Document()
    p = _mk_para(doc, [
        ("姓", False), (" ", False), ("名：", False), (" ", True), ("许明英", True),
        ("性", False),
        ("年", False), (" ", False), ("龄：", False), (" ", True), ("50", True),
        ("职", False),
    ])
    p2 = _mk_para(doc, [("别：", False), (" ", True), ("\t", True)])
    p3 = _mk_para(doc, [("务：", False), (" ", True), ("\t", True)])
    from services.docx_format_doctor import heal_orphan_split_labels

    before_chars = sorted(re.sub(r"\s+", "", p.text + p2.text + p3.text))
    n = heal_orphan_split_labels(doc)
    assert n == 2
    assert p2.text.startswith("性别：")
    assert p3.text.startswith("职务：")
    assert "性" not in p.text.replace("姓", "") or "性年" not in p.text  # 孤字已搬走
    assert "\n" in p.text  # 原位补了换行,姓名/年龄恢复两行
    after_chars = sorted(re.sub(r"\s+", "", p.text + p2.text + p3.text))
    assert before_chars == after_chars  # 非空白字符一个不多不少


def test_orphan_rejoined_prefill_empty_slots() -> None:
    """填前状态(槽还是带线空白、值未填)也要能归位——本 healer 就跑在填值前。

    回归:曾要求孤字前是"带线的已填值",填前空槽不满足 → 生产上永不触发(萧县实测)。
    """
    doc = Document()
    p = _mk_para(doc, [
        ("姓", False), (" ", False), ("名：", False), (" \t", True),  # 空槽(带线空白)
        ("性", False),
        ("年", False), (" ", False), ("龄：", False), (" \t", True),
        ("职", False),
    ])
    p2 = _mk_para(doc, [("别：", False), (" \t", True)])
    p3 = _mk_para(doc, [("务：", False), (" \t", True)])
    from services.docx_format_doctor import heal_orphan_split_labels

    n = heal_orphan_split_labels(doc)
    assert n == 2
    assert p2.text.startswith("性别：")
    assert p3.text.startswith("职务：")
    assert "性" not in p.text and "职" not in p.text  # 孤字都搬走了


def test_orphan_guard_normal_single_char_not_moved() -> None:
    """"姓 名："里的"姓"(前面没有带线值)绝不被搬走——哪怕后文恰有"名："段。"""
    doc = Document()
    p = _mk_para(doc, [("姓", False), (" ", False), ("名：", False), (" ", True), ("许明英", True)])
    p2 = _mk_para(doc, [("名：", False), (" ", True)])
    from services.docx_format_doctor import heal_orphan_split_labels

    n = heal_orphan_split_labels(doc)
    assert n == 0
    assert p.text.startswith("姓 名：")
    assert p2.text.startswith("名：")


def test_run_format_doctor_never_raises(monkeypatch) -> None:
    """healer 崩了也不阻断出标,报告记 0。"""
    import services.docx_format_doctor as m

    def _boom(document, profile=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(m, "_HEALERS", (("underline_slots", _boom),))
    report = m.run_format_doctor(Document())
    assert report == {"underline_slots": 0}


def test_filler_blank_runs_collapsed_but_slots_kept() -> None:
    """连续≥4个真空段压缩到2;带制表位的空槽段(日期下划线槽)绝不删。"""
    from services.docx_format_doctor import heal_filler_blank_runs

    doc = Document()
    doc.add_paragraph("正文")
    for _ in range(6):
        doc.add_paragraph("")
    slot = doc.add_paragraph()
    slot.add_run("\t")  # 空槽段(只有制表位)
    doc.add_paragraph("下一节")
    n = heal_filler_blank_runs(doc)
    assert n == 4  # 6个空段 → 留2删4
    texts = [p.text for p in doc.paragraphs]
    assert "正文" in texts and "下一节" in texts
    assert any("\t" in p.text for p in doc.paragraphs)  # 空槽段还在


def _set_spacing(p, line, rule):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    ppr = p._p.get_or_add_pPr()
    sp = ppr.find(qn("w:spacing"))
    if sp is None:
        sp = OxmlElement("w:spacing")
        ppr.append(sp)
    sp.set(qn("w:line"), str(line))
    sp.set(qn("w:lineRule"), rule)


def _spacing_of(p):
    from docx.oxml.ns import qn
    sp = p._p.get_or_add_pPr().find(qn("w:spacing"))
    return sp.get(qn("w:lineRule")), sp.get(qn("w:line"))


def test_line_spacing_unclips_exact_and_evens_loose() -> None:
    """福昕叠行修复:固定行高(exact,小于单倍)→自动且不小于240;过松(>300)→收单倍;文字不动。"""
    from services.docx_format_doctor import heal_line_spacing

    doc = Document()
    p_clip = doc.add_paragraph("被压叠的密集段落文字保持不变")
    _set_spacing(p_clip, 225, "exact")          # 固定行高偏小 → 叠行
    p_loose = doc.add_paragraph("过松的行")
    _set_spacing(p_loose, 397, "auto")          # >1.25倍 → 过松
    p_ok = doc.add_paragraph("正常单倍不动")
    _set_spacing(p_ok, 240, "auto")

    n = heal_line_spacing(doc)
    assert n == 2  # 只动叠行+过松两段
    assert _spacing_of(p_clip) == ("auto", "240")   # 固定→自动,提到单倍
    assert _spacing_of(p_loose) == ("auto", "240")  # 过松→单倍
    assert _spacing_of(p_ok) == ("auto", "240")     # 本就单倍,没被动
    # 文字逐字不变(红线)
    assert p_clip.text == "被压叠的密集段落文字保持不变"


def test_line_spacing_fixes_table_cell_paragraphs() -> None:
    """表格单元格里的叠行也要治(福昕表单大量exact在单元格内)。"""
    from services.docx_format_doctor import heal_line_spacing

    doc = Document()
    t = doc.add_table(rows=1, cols=1)
    cp = t.cell(0, 0).paragraphs[0]
    cp.add_run("单元格内密集文字")
    _set_spacing(cp, 220, "exact")
    n = heal_line_spacing(doc)
    assert n == 1
    assert _spacing_of(cp) == ("auto", "240")


def test_signature_wrap_kills_fuxin_giant_indent() -> None:
    """落款折行修复(埇桥实测病例):右对齐+福昕大缩进(5486)+填了公司名 → 缩进砍0,
    一行排下;(签章)空槽段制表位画出页外 → 制表位收进来。左对齐段/小缩进段不动。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn as _qn
    from services.docx_format_doctor import heal_signature_wrap

    doc = Document()

    def _sig_para(text, left, tab_pos=None, align="right"):
        p = doc.add_paragraph(text)
        ppr = p._p.get_or_add_pPr()
        jc = OxmlElement("w:jc"); jc.set(_qn("w:val"), align); ppr.append(jc)
        ind = OxmlElement("w:ind"); ind.set(_qn("w:left"), str(left)); ppr.append(ind)
        if tab_pos:
            tabs = OxmlElement("w:tabs"); tab = OxmlElement("w:tab")
            tab.set(_qn("w:val"), "left"); tab.set(_qn("w:pos"), str(tab_pos))
            tabs.append(tab); ppr.append(tabs)
        return p, ind

    p1, ind1 = _sig_para("投 标 人： 安徽正奇建设有限公司（盖单位章）", 5486)
    p2, ind2 = _sig_para("法定代表人或其委托代理人： \t（签章）", 3806, tab_pos=8850)
    p3, ind3 = _sig_para("短日期行", 5486)          # 排得下,不动
    p4, ind4 = _sig_para("左对齐正文段落不许被碰,不管多长的文字都轮不到这个修", 5486, align="left")

    n = heal_signature_wrap(doc)
    assert n == 2  # 只修 p1(公司名超宽) + p2(制表位超页宽)
    assert ind1.get(_qn("w:left")) == "0"           # 大缩进砍0,右对齐仍贴右
    assert ind2.get(_qn("w:left")) == "0"
    tab_el = p2._p.find(_qn("w:pPr")).find(_qn("w:tabs")).find(_qn("w:tab"))
    assert int(tab_el.get(_qn("w:pos"))) < 8850     # 制表位收进页内
    assert ind3.get(_qn("w:left")) == "5486"        # 排得下的原样保真
    assert ind4.get(_qn("w:left")) == "5486"        # 左对齐段绝不碰
    assert p1.text == "投 标 人： 安徽正奇建设有限公司（盖单位章）"  # 文字红线
