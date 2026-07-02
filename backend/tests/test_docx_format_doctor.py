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


def test_run_format_doctor_never_raises(monkeypatch) -> None:
    """healer 崩了也不阻断出标,报告记 0。"""
    import services.docx_format_doctor as m

    def _boom(document, profile=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(m, "_HEALERS", (("underline_slots", _boom),))
    report = m.run_format_doctor(Document())
    assert report == {"underline_slots": 0}
