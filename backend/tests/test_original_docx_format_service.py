from pathlib import Path

from docx import Document

from services.original_docx_format_service import (
    PDF_PAGE_MARKER_PREFIX,
    build_original_format_docx,
    build_original_format_docx_from_pdf,
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
