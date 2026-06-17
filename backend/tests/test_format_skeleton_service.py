"""format_skeleton_service 格式页提取测试(去重 TOC 幻影、把子条款留在所属页内)。

注:render_*/skeleton 等老的"文本重建骨架"函数已删(被 v2 照抄原格式取代,生产零调用),
对应测试一并移除;此文件只覆盖仍在用的 extract_format_pages。"""


def test_extract_format_pages_dedupes_local_toc_phantom_nodes() -> None:
    from services.format_skeleton_service import extract_format_pages

    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    目 录
    一、投标函
    二、法定代表人身份证明或授权委托书
    三、联合体协议书（如有）
    一、投标函
    致：（招标人）
    我方已仔细研究（招标项目名称）招标文件。
    投 标 人： （盖单位章）
    二、法定代表人身份证明或授权委托书
    投 标 人：
    附：法定代表人身份证正反面扫描件
    """

    pages = extract_format_pages(tender_text)["commercial"]
    titles = [page.title for page in pages]

    assert titles.count("一、投标函") == 1
    bid_letter = next(page for page in pages if page.title == "一、投标函")
    assert "我方已仔细研究" in bid_letter.raw_template


def test_extract_format_pages_keeps_bank_guarantee_clauses_inside_deposit_page() -> None:
    from services.format_skeleton_service import extract_format_pages

    tender_text = """
    第八章 投标文件格式
    投标文件（商务文件）
    四、投标保证金
    （一）投标保函示范文本
    编号：
    致：受益人（招标人）名称
    一、开立人理解根据招标条件，投标人必须提交一份投标保函（以下简称“本保函”），以担保投标人诚信履行义务。
    二、开立人在投标人发生以下情形时承担保证担保责任：
    （1）投标人在投标有效期内撤销投标文件；
    九、本保函自我方法定代表人或授权代表签字并加盖公章之日起生效。
    开立人： （公章）
    五、项目管理机构
    拟为承包本标段工程设立的组织机构以框图方式表示。
    """

    pages = extract_format_pages(tender_text)["commercial"]
    titles = [page.title for page in pages]

    assert "四、投标保证金" in titles
    assert not any(title.startswith("一、开立人理解") for title in titles)
    deposit = next(page for page in pages if page.title == "四、投标保证金")
    assert "九、本保函" in deposit.raw_template
