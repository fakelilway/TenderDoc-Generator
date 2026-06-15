from pathlib import Path

from docx import Document

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from services.original_docx_format_service import (
    PDF_PAGE_MARKER_PREFIX,
    _drop_spurious_stream_tables,
    _fill_known_table_cells,
    _table_label_value,
    build_original_format_docx,
    build_original_format_docx_from_pdf,
    build_original_format_docx_from_pdf_editable,
    build_original_format_docx_from_pdf_with_fields,
)


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
    assert _table_label_value("投标人名称", profile) == "安徽正奇建设有限公司"
    assert _table_label_value("统一社会信用代码", profile) == "91340100578516708N"
    assert _table_label_value("注册资本", profile) == "10060万元人民币"
    # 另一个人 / 日期 / 无对应字段 → 不填
    assert _table_label_value("技术负责人", profile) == ""
    assert _table_label_value("成立时间", profile) == ""
    assert _table_label_value("员工总人数：", profile) == ""
    assert _table_label_value("随便什么标题", profile) == ""


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
    assert _fill_value_for_label("址：", profile) == "合肥市某路1号"  # 地 址 → '址：'
    assert _fill_value_for_label("名：", profile) == "张三"  # 姓 名 → '名：'
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
