from pathlib import Path

from docx import Document

from services.original_docx_format_service import (
    PDF_PAGE_MARKER_PREFIX,
    build_original_format_docx,
    build_original_format_docx_from_pdf,
    build_original_format_docx_from_pdf_editable,
    build_original_format_docx_from_pdf_with_fields,
)


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
