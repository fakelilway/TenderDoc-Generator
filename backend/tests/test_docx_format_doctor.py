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
