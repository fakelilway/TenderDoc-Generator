from pathlib import Path

from docx import Document

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from services.original_docx_format_service import (
    PDF_PAGE_MARKER_PREFIX,
    _drop_spurious_stream_tables,
    _fill_known_table_cells,
    _is_blank_or_placeholder,
    _fill_value_for_label,
    _looks_like_next_chapter_page,
    _looks_like_other_volume_start,
    _table_label_value,
    build_original_format_docx,
    unfilled_known_fields,
    build_original_format_docx_from_pdf,
    build_original_format_docx_from_pdf_editable,
    build_original_format_docx_from_pdf_with_fields,
)


def test_next_chapter_ignores_midsentence_crossreference() -> None:
    # 实测招标#122 p105：跨引用"…招标文件第二章…"不得当成新章(会切掉资格审查后半+八)
    assert not _looks_like_next_chapter_page(
        "106备注注：1.投标人应根据招标文件第二章“投标人须知”第3.5.1项的要求在本表后附材料。"
    )
    # 页首(带页码)的真章标题才算边界
    assert _looks_like_next_chapter_page("106第八章评标办法投标人应仔细阅读")
    assert _looks_like_next_chapter_page("第三章投标人须知")
    # 格式章自身不作为结束边界
    assert not _looks_like_next_chapter_page("第八章投标文件格式")


def test_other_volume_start_marks_commercial_end() -> None:
    # 技术/报价卷起始 → 商务格式章到此为止
    assert _looks_like_other_volume_start("（标段名称）施工招标投标文件（技术文件）投标人：（盖单位章）")
    assert _looks_like_other_volume_start("（标段名称）施工招标投标文件（报价文件）投标人")
    # 商务卷自身、普通表单不触发
    assert not _looks_like_other_volume_start("（标段名称）施工招标投标文件（商务文件）")
    assert not _looks_like_other_volume_start("三、联合体协议书（所有成员单位名称）自愿组成")


def _add_cell_borders(cell) -> None:
    """Give a cell real single borders (mimics pdf2docx's true-table cells)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for side in ("top", "bottom", "start", "end"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        borders.append(el)
    tc_pr.append(borders)


def test_drop_spurious_stream_tables_flattens_borderless_small_tables() -> None:
    doc = Document()
    spurious = doc.add_table(rows=1, cols=2)  # 填空行被误判:2格、无边框
    spurious.cell(0, 0).text = "1.我方已仔细研究"
    spurious.cell(0, 1).text = "标段招标文件的全部内容。"
    big = doc.add_table(rows=15, cols=10)  # 真表(基本情况表式):>2格 → 保留
    big.cell(0, 0).text = "投标人名称"

    dropped = _drop_spurious_stream_tables(doc)

    assert dropped == 1
    assert len(doc.tables) == 1  # 大表保留
    assert any(
        "我方已仔细研究" in p.text and "招标文件的全部内容" in p.text
        for p in doc.paragraphs
    )  # 假表内容已还原成连续段落


def test_drop_spurious_stream_tables_keeps_small_bordered_table() -> None:
    doc = Document()
    bordered = doc.add_table(rows=2, cols=1)  # 2格但有真边框(如项目管理机构图说明)
    _add_cell_borders(bordered.cell(0, 0))
    bordered.cell(0, 0).text = "拟为承包本标段以框图方式表示。"
    bordered.cell(1, 0).text = "说明"

    dropped = _drop_spurious_stream_tables(doc)

    assert dropped == 0
    assert len(doc.tables) == 1  # 有边框的真表不动


def test_table_label_value_maps_known_and_skips_others() -> None:
    profile = {
        "company_name": "安徽正奇建设有限公司",
        "credit_code": "91340100578516708N",
        "legal_representative": "许明英",
        "registered_capital": "10060万元人民币",
    }
    profile["project_manager_name"] = "江舟"
    assert _table_label_value("投标人名称", profile) == "安徽正奇建设有限公司"
    assert _table_label_value("统一社会信用代码", profile) == "91340100578516708N"
    assert _table_label_value("注册资本", profile) == "10060万元人民币"
    assert _table_label_value("项目经理", profile) == "江舟"
    assert _table_label_value("项目经理姓名", profile) == "江舟"
    # 另一个人 / 日期 / 无对应字段 → 不填
    assert _table_label_value("技术负责人", profile) == ""
    assert _table_label_value("成立时间", profile) == ""
    assert _table_label_value("员工总人数：", profile) == ""
    assert _table_label_value("随便什么标题", profile) == ""


def _solid_png(rgb: tuple[int, int, int], size: tuple[int, int] = (80, 80)) -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.new("RGBA", size, (*rgb, 255))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_image_is_seal_detects_red_stamp_only() -> None:
    from services.original_docx_format_service import _image_is_seal

    assert _image_is_seal(_solid_png((220, 20, 20))) is True  # 红章
    assert _image_is_seal(_solid_png((250, 250, 250))) is False  # 白底
    assert _image_is_seal(_solid_png((15, 15, 15))) is False  # 黑字
    assert _image_is_seal(_solid_png((20, 40, 200))) is False  # 蓝线附表图


def test_strip_seal_images_removes_seals_keeps_rest() -> None:
    """回归(实测真招标商务卷):福昕把招标人/代理红章照搬进来,乱盖一片;只删红章,
    保留文字、表格、非章图(附表线框/页面图)。"""
    from io import BytesIO

    from docx import Document
    from docx.shared import Cm

    from services.original_docx_format_service import _strip_seal_images

    doc = Document()
    doc.add_paragraph("投标人：（盖单位章）")
    doc.add_paragraph().add_run().add_picture(
        BytesIO(_solid_png((220, 20, 20))), width=Cm(3)
    )  # 红章
    doc.add_paragraph("附表二 分项工程进度率计划")
    doc.add_paragraph().add_run().add_picture(
        BytesIO(_solid_png((20, 40, 200))), width=Cm(3)
    )  # 蓝线附表图(非章)

    before = len(doc.element.findall(".//" + qn("w:drawing")))
    removed = _strip_seal_images(doc)
    after = len(doc.element.findall(".//" + qn("w:drawing")))

    assert removed == 1
    assert before - after == 1  # 只删了红章,蓝图还在
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "盖单位章" in text and "附表二" in text  # 文字完整


def test_fill_value_for_label_no_single_char_misfill() -> None:
    """回归:PDF 路径原用单字键('名'/'址')会把 项目名称→法人、邮政编码→地址 乱填。
    改走统一稳健映射后,这些歧义/无对应标签一律留空,只精确标签才填。"""
    profile = {
        "company_name": "安徽正奇建设有限公司",
        "legal_representative": "许明英",
        "registered_address": "安徽省合肥市…",
    }
    # 单字误匹配已消除
    assert _fill_value_for_label("项目名称", profile) == ""  # 旧:误=法人
    assert _fill_value_for_label("邮政编码", profile) == ""  # 旧:误=地址
    assert _fill_value_for_label("姓名", profile) == ""  # 歧义 → 不填
    # 精确标签 + 扩别名 仍正确
    assert _fill_value_for_label("法定代表人", profile) == "许明英"
    assert _fill_value_for_label("单位名称", profile) == "安徽正奇建设有限公司"


def test_table_label_value_expanded_aliases() -> None:
    """扩标签别名:招标各家措辞(企业名称/公司名称/法人代表/住所…)都能对上字段。"""
    profile = {
        "company_name": "安徽正奇建设有限公司",
        "legal_representative": "许明英",
        "registered_address": "安徽省合肥市…",
    }
    for label in ("企业名称", "公司名称", "单位名称", "投标人全称"):
        assert _table_label_value(label, profile) == "安徽正奇建设有限公司", label
    assert _table_label_value("法人代表", profile) == "许明英"
    assert _table_label_value("住所", profile).startswith("安徽省")


def test_unfilled_known_fields_flags_recognized_but_empty() -> None:
    """缺字段显式告警:认得标签但档案无值 → 列出来,别静默留空。"""
    from docx import Document

    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "投标人名称"
    table.cell(0, 1).text = ""
    table.cell(1, 0).text = "开户银行"  # 档案缺 → 应被标记
    table.cell(1, 1).text = ""
    table.cell(2, 0).text = "联系电话"  # 档案缺 → 应被标记
    table.cell(2, 1).text = ""
    profile = {"company_name": "安徽正奇建设有限公司"}  # 有公司名,缺银行/电话

    missing = dict((label, key) for label, key in unfilled_known_fields(doc, profile))
    keys = set(missing.values())
    assert "bank_name" in keys and "contact_phone" in keys
    assert "company_name" not in keys  # 已填的不算缺


def test_table_label_value_broad_key_does_not_overfill() -> None:
    """回归(实测 122 商务卷):宽泛主体词("投标人"/"项目经理")含在标签里 ≠ 就该填它的
    名字。子字段标签必须留空待人工,绝不能拿公司名/项目经理名瞎填(废标级错误)。"""
    profile = {
        "company_name": "安徽正奇建设有限公司",
        "credit_code": "91340100578516708N",
        "project_manager_name": "江舟",
    }
    # ❌ 原来全被"投标人"/"项目经理"子串命中、瞎填成公司名或"江舟"
    for wrong in (
        "投标人响应资质", "投标人资格业绩", "投标人加分业绩", "投标人荣誉",
        "项目经理身份证号码", "项目经理证书名称", "项目经理证书编号", "项目经理荣誉",
    ):
        assert _table_label_value(wrong, profile) == "", wrong
    # ✓ "要名字"的复合标签仍正确填(联合体牵头人=投标人本身)
    assert (
        _table_label_value("独立投标人或联合体牵头人名称", profile)
        == "安徽正奇建设有限公司"
    )
    # ✓ 最长匹配:具体字段胜过宽泛"投标人",信用代码不再被填成公司名
    assert (
        _table_label_value("独立投标人或联合体牵头人统一社会信用代码", profile)
        == "91340100578516708N"
    )


def test_fill_known_table_cells_fills_adjacent_empty_only() -> None:
    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "投标人名称"  # (0,1) 空 → 应填
    table.cell(1, 0).text = "统一社会信用代码"
    table.cell(1, 1).text = "已有值"  # 已填 → 不覆盖
    table.cell(2, 0).text = "技术负责人"  # 另一个人 → 跳过,(2,1) 保持空

    profile = {"company_name": "安徽正奇建设有限公司", "credit_code": "91X"}
    filled = _fill_known_table_cells(doc, profile)

    assert table.cell(0, 1).text == "安徽正奇建设有限公司"
    assert table.cell(1, 1).text == "已有值"  # 未被覆盖
    assert table.cell(2, 1).text.strip() == ""  # 技术负责人行未填
    assert filled == 1


def test_fill_known_table_cells_fills_through_sublabel() -> None:
    # 法定代表人 | 姓名 | [空] —— 跨过"姓名"子标签,把值填进真正的值格
    doc = Document()
    table = doc.add_table(rows=1, cols=3)
    table.cell(0, 0).text = "法定代表人"
    table.cell(0, 1).text = "姓名"

    _fill_known_table_cells(doc, {"legal_representative": "许明英"})

    assert table.cell(0, 2).text.strip() == "许明英"


def test_fill_known_table_cells_skips_second_person_sublabel_row() -> None:
    # 技术负责人 是另一个人(在 skip 列),其"姓名"值格不应被填法定代表人
    doc = Document()
    table = doc.add_table(rows=1, cols=3)
    table.cell(0, 0).text = "技术负责人"
    table.cell(0, 1).text = "姓名"

    _fill_known_table_cells(doc, {"legal_representative": "许明英"})

    assert table.cell(0, 2).text.strip() == ""


def test_fill_known_table_cells_noop_when_profile_empty() -> None:
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "投标人名称"
    assert _fill_known_table_cells(doc, {}) == 0
    assert table.cell(0, 1).text.strip() == ""


def test_fill_known_table_cells_reconstructs_fragmented_label() -> None:
    # 中文公文表常把"投标人："逐字对齐拆成 投|标|人： 三格 + 空值格;
    # 单格匹配不到,碎标签重组后应把 company_name 填进值格。
    doc = Document()
    table = doc.add_table(rows=1, cols=4)
    table.cell(0, 0).text = "投"
    table.cell(0, 1).text = "标"
    table.cell(0, 2).text = "人："
    filled = _fill_known_table_cells(doc, {"company_name": "安徽正奇建设有限公司"})
    assert table.cell(0, 3).text.strip() == "安徽正奇建设有限公司"
    assert filled == 1


def test_fill_known_table_cells_fragmented_does_not_false_match() -> None:
    # 短格拼起来不构成已知标签 → 绝不误填(防碎标签重组造出假标签)。
    doc = Document()
    table = doc.add_table(rows=1, cols=4)
    table.cell(0, 0).text = "序"
    table.cell(0, 1).text = "号"
    table.cell(0, 2).text = "A1"
    filled = _fill_known_table_cells(doc, {"company_name": "安徽正奇建设有限公司"})
    assert table.cell(0, 3).text.strip() == ""
    assert filled == 0


def test_build_original_format_docx_copies_format_tables_verbatim(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "tender.docx"
    source = Document()
    source.add_paragraph("第一章 招标公告")
    source.add_paragraph("第八章 投标文件格式")
    source.add_paragraph("投标文件（商务文件）")
    source.add_paragraph("（一）投标人基本情况表")
    table = source.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    table.cell(0, 0).text = "投标人名称"
    table.cell(0, 1).merge(table.cell(0, 2))
    table.cell(0, 1).text = "（投标人名称）"
    table.cell(1, 0).text = "注册地址"
    table.cell(1, 1).text = "邮政编码"
    table.cell(1, 2).text = "________"
    table.cell(2, 0).text = "备注"
    table.cell(2, 1).merge(table.cell(2, 2))
    table.cell(2, 1).text = "________"
    source.add_paragraph("第九章 评标办法")
    source.save(source_path)

    output_path = tmp_path / "copied.docx"
    build_original_format_docx(
        source_path.read_bytes(),
        output_path,
        profile={"company_name": "安徽正奇建设有限公司"},
    )

    copied = Document(output_path)
    texts = [paragraph.text for paragraph in copied.paragraphs]
    assert "第八章 投标文件格式" in texts
    assert "第九章 评标办法" not in texts
    assert len(copied.tables) == 1
    copied_table = copied.tables[0]
    assert len(copied_table.rows) == 3
    assert len(copied_table.columns) == 3
    assert copied_table.cell(0, 0).text == "投标人名称"
    assert copied_table.cell(0, 1).text == "安徽正奇建设有限公司"
    assert copied_table.cell(0, 2).text == "安徽正奇建设有限公司"


def test_build_original_format_docx_from_pdf_embeds_format_pages_as_images(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import fitz

    source_path = tmp_path / "tender.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Chapter 1 Notice")
    page = pdf.new_page()
    page.insert_text((72, 72), "Chapter 8 Bid Format")
    page.insert_text((72, 120), "Commercial Volume")
    page.insert_text((72, 168), "Bidder Basic Information Table")
    page = pdf.new_page()
    page.insert_text((72, 72), "Bid Letter")
    pdf.save(source_path)
    pdf.close()

    monkeypatch.setattr(
        "services.original_docx_format_service._find_format_page_range_in_pdf",
        lambda _path: (1, 3),
    )

    output_path = tmp_path / "copied_from_pdf.docx"
    build_original_format_docx_from_pdf(source_path.read_bytes(), output_path)

    copied = Document(output_path)
    assert len(copied.inline_shapes) == 2
    assert len(copied.tables) == 0
    xml = copied.element.xml
    assert "w:txbxContent" in xml
    assert PDF_PAGE_MARKER_PREFIX in xml
    assert "Chapter 8 Bid Format" in xml


def test_build_original_format_docx_from_pdf_editable_produces_real_text(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """pdf2docx path reconstructs editable text (not an image), with no page markers
    so it routes through the keyword-based DOCX volume split."""
    import fitz

    source_path = tmp_path / "tender.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Chapter 1 Notice")
    page = pdf.new_page()
    page.insert_text((72, 72), "Chapter 8 Bid Format")
    page.insert_text((72, 120), "Commercial Volume Bidder Table")
    pdf.save(source_path)
    pdf.close()

    monkeypatch.setattr(
        "services.original_docx_format_service._find_format_page_range_in_pdf",
        lambda _path: (1, 2),
    )

    output_path = tmp_path / "editable_from_pdf.docx"
    build_original_format_docx_from_pdf_editable(source_path.read_bytes(), output_path)

    doc = Document(output_path)
    all_text = "\n".join(p.text for p in doc.paragraphs)
    # Real editable text, not an embedded page image.
    assert "Bid Format" in all_text
    assert len(doc.inline_shapes) == 0
    # No PDF page markers — editable DOCX rides the keyword split, not page blocks.
    assert PDF_PAGE_MARKER_PREFIX not in doc.element.xml


def test_build_pdf_with_fields_bakes_values_no_vml_overlay(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Each format page is a pixel-perfect inline image (no VML text-box overlay,
    no page markers) — KB values are baked onto the page before rasterizing so it
    renders in any viewer (Pages/LibreOffice/Word)."""
    import fitz

    source_path = tmp_path / "tender.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Chapter 8 Bid Format")
    page = pdf.new_page()
    page.insert_text((72, 100), "投标人：")
    page.draw_line(fitz.Point(140, 104), fitz.Point(400, 104))
    pdf.save(source_path)
    pdf.close()

    monkeypatch.setattr(
        "services.original_docx_format_service._find_format_page_range_in_pdf",
        lambda _path: (1, 2),
    )

    output_path = tmp_path / "with_fields.docx"
    build_original_format_docx_from_pdf_with_fields(
        source_path.read_bytes(),
        output_path,
        profile={"company_name": "安徽正奇建设有限公司"},
    )

    doc = Document(output_path)
    xml = doc.element.xml
    # Pixel-perfect base image present; no VML overlay, no page markers.
    assert len(doc.inline_shapes) == 1
    assert "txbxContent" not in xml
    assert PDF_PAGE_MARKER_PREFIX not in xml
    # (Baking of CJK values is exercised by the real-tender path / unit tests;
    # fitz's default font cannot render CJK labels into a synthetic test PDF.)


def test_fill_value_for_label_maps_and_skips() -> None:
    from services.original_docx_format_service import _fill_value_for_label

    profile = {
        "company_name": "安徽正奇建设有限公司",
        "registered_address": "合肥市某路1号",
        "legal_representative": "张三",
    }
    assert _fill_value_for_label("投标人：", profile) == "安徽正奇建设有限公司"
    # 整标签照填(改走统一稳健映射后,用全称而非单字短键)
    assert _fill_value_for_label("注册地址：", profile) == "合肥市某路1号"
    assert _fill_value_for_label("法定代表人：", profile) == "张三"
    # 单字短键已废:'址'/'名' 单独出现太歧义(项目名称/邮政编码会被乱配)→ 不填
    assert _fill_value_for_label("址：", profile) == ""
    assert _fill_value_for_label("名：", profile) == ""
    # Segmented / unmapped blanks stay empty (editable but not auto-filled).
    assert _fill_value_for_label("成立时间：", profile) == ""
    assert _fill_value_for_label("别：", profile) == ""  # 性别
    assert _fill_value_for_label("日　期：", profile) == ""
    assert _fill_value_for_label(None, profile) == ""


def test_nearest_left_label_matches_same_row() -> None:
    from services.original_docx_format_service import _nearest_left_label

    labels = [("投标人：", 114.0, 141.0, 162.0), ("单位性质：", 114.0, 164.0, 174.0)]
    # underline on the 投标人 row (y≈153), starting right of the label
    assert _nearest_left_label(174.0, 153.0, labels) == "投标人："
    # underline far above any label → no match
    assert _nearest_left_label(174.0, 50.0, labels) is None


def test_fill_personnel_table_fills_project_manager_row() -> None:
    from services.original_docx_format_service import _fill_personnel_table

    doc = Document()
    table = doc.add_table(rows=4, cols=6)
    # 表头第1行
    table.cell(0, 0).text = "职务"
    table.cell(0, 1).text = "姓名"
    table.cell(0, 2).text = "职称"
    table.cell(0, 3).text = "执业或职业资格证明"
    # 表头第2行(子列)
    table.cell(1, 3).text = "证书名称"
    table.cell(1, 4).text = "级别"
    table.cell(1, 5).text = "证号"
    # 第3、4行为空数据行

    profile = {"project_manager_name": "江舟", "project_manager_cert": "皖1342006200803161"}
    assert _fill_personnel_table(doc, profile) is True
    assert table.cell(2, 0).text == "项目经理"
    assert table.cell(2, 1).text == "江舟"
    assert table.cell(2, 5).text == "皖1342006200803161"


def test_fill_personnel_table_noop_without_pm() -> None:
    from services.original_docx_format_service import _fill_personnel_table

    doc = Document()
    table = doc.add_table(rows=3, cols=6)
    table.cell(0, 0).text = "职务"
    table.cell(0, 1).text = "姓名"
    table.cell(1, 5).text = "证号"
    assert _fill_personnel_table(doc, {}) is False
    assert table.cell(2, 1).text.strip() == ""


# ── #8 占位填空:省略号/点线签字线该当"空"来填,但绝不覆盖真值/孤立短横/句号 ──────
def test_is_blank_or_placeholder_treats_fill_lines_as_blank() -> None:
    # 真·空 / 下划线 / 全角空格 / 制表符:占位,单个即算
    for blank in ["", "   ", "_____", "＿＿＿", "　", "\t", "…", "‥"]:
        assert _is_blank_or_placeholder(blank) is True, blank
    # 点线/破折号签字线:连续≥2 才算占位(实测产物里的真实漏填形状)
    for leader in ["……", "....", "．．．", "- - -", "————", "··········"]:
        assert _is_blank_or_placeholder(leader) is True, leader


def test_is_blank_or_placeholder_never_eats_real_values() -> None:
    # 真值绝不能被判空(否则会被公司档案值覆盖)
    for real in [
        "安徽正奇建设集团有限公司", "江舟", "0551-65650939",
        "2022.03", "5.4m", "0-50分", "1.1.4.5", "91340000X",
    ]:
        assert _is_blank_or_placeholder(real) is False, real
    # 孤立单个 短横/点/间隔号 = 人工填的"无/不适用",不判空
    for nil in ["—", "-", "－", "·", "．", "/"]:
        assert _is_blank_or_placeholder(nil) is False, nil
    # 句号(及句号串)是真标点,永不判空
    for dot in ["。", "。。。", "以上。"]:
        assert _is_blank_or_placeholder(dot) is False, dot


def test_fill_known_table_cells_fills_ellipsis_placeholder() -> None:
    # 核心 bug:值格是省略号/点线占位(福昕产物实测存在 U+2026),旧 _TABLE_BLANK_RE
    # 只认下划线 → 判为非空 → 跳过留空。现应识别为占位并填入。
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "投标人名称"
    table.cell(0, 1).text = "…"  # 省略号占位
    table.cell(1, 0).text = "统一社会信用代码"
    table.cell(1, 1).text = "________"  # 下划线占位(旧逻辑也能填)

    filled = _fill_known_table_cells(
        doc, {"company_name": "安徽正奇建设有限公司", "credit_code": "91X"}
    )
    assert table.cell(0, 1).text == "安徽正奇建设有限公司"
    assert table.cell(1, 1).text == "91X"
    assert filled == 2


def test_fill_known_table_cells_keeps_nil_dash_answer() -> None:
    # 值格是人工填的"—"(无/不适用)→ 不是占位,绝不覆盖
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "投标人名称"
    table.cell(0, 1).text = "—"

    filled = _fill_known_table_cells(doc, {"company_name": "安徽正奇建设有限公司"})
    assert table.cell(0, 1).text == "—"  # 真答案保留
    assert filled == 0


# ── #9 接入可推导字段:项目名称/工期 从招标解析(combined_profile 中文键)填进商务卷 ──
def test_table_label_value_fills_project_derived_fields() -> None:
    # combined_profile 里项目级字段是中文键(v2_generation_service.project_fields)
    combined = {
        "company_name": "安徽正奇建设有限公司",
        "项目名称": "XX县2025年农村公路提质改造联网路工程",
        "工期": "90日历天",
        "project_manager_name": "江舟",
    }
    assert _table_label_value("项目名称", combined) == combined["项目名称"]
    assert _table_label_value("工程名称", combined) == combined["项目名称"]
    assert _table_label_value("计划工期", combined) == "90日历天"
    assert _table_label_value("工期", combined) == "90日历天"
    # 关键防撞:"项目名称"不得把"项目经理"格抢成项目名(仍填项目经理名)
    assert _table_label_value("项目经理", combined) == "江舟"
    assert _table_label_value("项目经理姓名", combined) == "江舟"


def test_fill_known_table_cells_fills_project_name_and_duration() -> None:
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目名称"
    table.cell(0, 1).text = "…"  # 占位
    table.cell(1, 0).text = "计划工期"  # (1,1) 空

    filled = _fill_known_table_cells(
        doc, {"项目名称": "XX路网工程", "工期": "90日历天"}
    )
    assert table.cell(0, 1).text == "XX路网工程"
    assert table.cell(1, 1).text == "90日历天"
    assert filled == 2


# ── 投标函内联空(用户实测):工程质量/安全目标/工期 写在正文里 "标签：<tab>" ──────
def _bid_letter_para(doc):
    p = doc.add_paragraph()
    for t in ["3", ".", "工程质量：", " ", "\t", "，安全目标：", " ", "\t",
              "，工期", "：", " ", "\t", "日历天", "。"]:
        p.add_run(t)
    return p


def test_fill_inline_labeled_blanks_fills_bid_letter_prose() -> None:
    from services.original_docx_format_service import _fill_inline_labeled_blanks
    doc = Document()
    _bid_letter_para(doc)
    n = _fill_inline_labeled_blanks(doc, {
        "质量": "符合国家现行工程质量验收标准规范合格标准",
        "安全": "无安全责任事故发生",
        "工期": "90日历天",
    })
    norm = doc.paragraphs[0].text.replace(" ", "")
    assert n == 3
    assert "工程质量：符合国家现行工程质量验收标准规范合格标准" in norm
    assert "安全目标：无安全责任事故发生" in norm
    assert "工期：90日历天。" in norm
    assert "日历天日历天" not in norm  # 单位不重复


def test_fill_inline_blanks_ignores_unlabeled_tabs() -> None:
    from services.original_docx_format_service import _fill_inline_labeled_blanks
    doc = Document()
    p = doc.add_paragraph()
    for t in ["目录", "\t", "第1页"]:
        p.add_run(t)
    assert _fill_inline_labeled_blanks(doc, {"质量": "X"}) == 0
    assert doc.paragraphs[0].text == "目录\t第1页"  # 无标签的 tab 不动


def test_fill_inline_blanks_does_not_overwrite_existing_value() -> None:
    from services.original_docx_format_service import _fill_inline_labeled_blanks
    doc = Document()
    p = doc.add_paragraph()
    for t in ["工期：", "90日历天", "。"]:  # 已有值、无 tab 槽
        p.add_run(t)
    assert _fill_inline_labeled_blanks(doc, {"工期": "45日历天"}) == 0
    assert "90日历天" in doc.paragraphs[0].text  # 原值保留,不被覆盖


def test_fill_inline_blanks_fills_signature_names_only() -> None:
    """投标函签署块:投标人/法定代表人 印姓名,但（盖单位章）/（签字）文字保留(不代盖代签)。"""
    from services.original_docx_format_service import _fill_inline_labeled_blanks
    doc = Document()
    p = doc.add_paragraph()
    for t in ["投标人：", " ", "\t", "（盖单位章）", "法定代表人：", " ", "\t", "（签字）"]:
        p.add_run(t)
    n = _fill_inline_labeled_blanks(
        doc, {"company_name": "安徽正奇建设有限公司", "legal_representative": "许明英"}
    )
    txt = doc.paragraphs[0].text
    assert n == 2
    assert "投标人： 安徽正奇建设有限公司（盖单位章）" in txt
    assert "法定代表人： 许明英（签字）" in txt
    assert "（盖单位章）" in txt and "（签字）" in txt  # 盖章/签字位仍在,只印了名


def test_fill_inline_blanks_skips_委托代理人_ambiguous() -> None:
    """法定代表人或委托代理人:谁签不定 → 不自动填(endswith 不命中 法定代表人)。"""
    from services.original_docx_format_service import _fill_inline_labeled_blanks
    doc = Document()
    p = doc.add_paragraph()
    for t in ["法定代表人或委托代理人：", "\t", "（签字）"]:
        p.add_run(t)
    assert _fill_inline_labeled_blanks(doc, {"legal_representative": "许明英"}) == 0
    assert "\t" in doc.paragraphs[0].text  # 留空待人工
