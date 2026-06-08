from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn

from utils.docx_exporter import (
    build_export_filename,
    markdown_to_docx,
    split_bid_markdown,
)


def test_markdown_to_docx_exports_headings_paragraphs_bullets_and_table(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "bid.docx"
    markdown = """# 技术标书

## 施工组织设计

本章节说明施工部署。

- 质量控制
- 安全文明施工

| 项目 | 措施 |
| --- | --- |
| 质量 | 三检制 |
"""

    markdown_to_docx(markdown, output_path)

    assert output_path.exists()
    document = Document(output_path)
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert "技术标书" in texts
    assert "施工组织设计" in texts
    assert "本章节说明施工部署。" in texts
    assert len(document.tables) == 1
    assert document.tables[0].cell(1, 1).text == "三检制"


def test_markdown_to_docx_adds_cover_toc_header_and_page_numbers(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "bid.docx"
    markdown = """# 高层住宅投标文件

## 施工组织设计

施工部署与质量控制措施。
"""

    markdown_to_docx(
        markdown,
        output_path,
        title="高层住宅投标文件",
        subtitle="投标文件",
        cover=True,
        toc=True,
        header_text="高层住宅投标文件",
        page_numbers=True,
    )

    document = Document(output_path)
    texts = [paragraph.text for paragraph in document.paragraphs]
    # Cover title and table-of-contents heading are present.
    assert "高层住宅投标文件" in texts
    assert "目录" in texts
    # TOC field is embedded in the body and updates inside Word.
    assert "TOC" in document.element.xml
    # Running header carries the document title.
    assert document.sections[0].header.paragraphs[0].text == "高层住宅投标文件"
    # Footer carries a PAGE field for page numbering.
    footer_xml = document.sections[0].footer.paragraphs[0]._p.xml
    assert "PAGE" in footer_xml


def test_split_bid_markdown_routes_commercial_sections() -> None:
    markdown = """# 某项目投标文件

## 施工组织设计

施工部署。

## 项目管理机构

人员配置。

## 投标报价说明

报价构成。

## 资格审查资料

营业执照与资质。
"""

    volumes = split_bid_markdown(markdown)

    assert set(volumes) == {"技术标", "商务标"}
    assert "施工组织设计" in volumes["技术标"]
    assert "项目管理机构" in volumes["技术标"]
    assert "投标报价说明" in volumes["商务标"]
    assert "资格审查资料" in volumes["商务标"]
    # Each volume keeps a document-level title prefix.
    assert volumes["技术标"].startswith("# 某项目投标文件（技术标）")
    assert volumes["商务标"].startswith("# 某项目投标文件（商务标）")


def test_split_bid_markdown_single_volume_when_no_commercial_sections() -> None:
    markdown = """# 技术方案

## 施工组织设计

施工部署。
"""

    volumes = split_bid_markdown(markdown)

    assert set(volumes) == {"技术标"}


def test_build_export_filename_includes_name_and_version() -> None:
    assert (
        build_export_filename("高层 住宅/项目", version=2, kind="技术标")
        == "高层_住宅_项目_技术标_v2.docx"
    )
    assert build_export_filename("", version=0) == "投标文件_v1.docx"


def test_markdown_to_docx_uses_chinese_production_typography(tmp_path: Path) -> None:
    output_path = tmp_path / "bid.docx"
    markdown = """# 投标文件

## 第一章、施工组织设计

本工程采用分段流水施工，明确施工部署与资源配置。
"""

    markdown_to_docx(markdown, output_path)

    document = Document(output_path)
    normal = document.styles["Normal"]
    normal_rfonts = normal.element.rPr.rFonts
    # Body is 宋体 / Times New Roman at 小四 (12pt).
    assert normal_rfonts.get(qn("w:eastAsia")) == "SimSun"
    assert normal.font.size.pt == 12

    heading1 = document.styles["Heading 1"]
    assert heading1.element.rPr.rFonts.get(qn("w:eastAsia")) == "SimHei"
    assert heading1.font.bold is True

    # Body paragraphs carry a 2-character first-line indent.
    body = next(
        p for p in document.paragraphs if p.text.startswith("本工程采用分段流水施工")
    )
    assert body.paragraph_format.first_line_indent is not None
    assert body.paragraph_format.first_line_indent.pt == 24


def test_markdown_to_docx_can_apply_zhengqi_bid_style_profile(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "zhengqi.docx"
    markdown = """# 正奇格式投标文件

## 第一章、总体施工组织布置及规划

本工程采用分段流水施工，明确施工部署、资源配置、质量安全环保控制措施。

| 序号 | 项目 | 内容 |
| --- | --- | --- |
| 1 | 质量 | 执行三检制和样板引路制度 |
"""

    markdown_to_docx(
        markdown,
        output_path,
        title="正奇格式投标文件",
        subtitle="投标文件",
        cover=True,
        toc=True,
        header_text="正奇格式投标文件 施工组织设计",
        page_numbers=True,
        style_profile="zhengqi",
    )

    document = Document(output_path)
    normal = document.styles["Normal"]
    normal_rfonts = normal.element.rPr.rFonts
    assert normal_rfonts.get(qn("w:eastAsia")) == "SimSun"
    assert normal.font.size.pt == 14
    assert normal.paragraph_format.line_spacing_rule == WD_LINE_SPACING.EXACTLY
    assert normal.paragraph_format.line_spacing.pt == 32

    heading1 = document.styles["Heading 1"]
    assert heading1.element.rPr.rFonts.get(qn("w:eastAsia")) == "SimSun"
    assert heading1.font.size.pt == 18
    assert heading1.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER

    cover_title = next(
        paragraph for paragraph in document.paragraphs if paragraph.text == "正奇格式投标文件"
    )
    assert cover_title.runs[0].font.size.pt == 36

    body = next(
        paragraph for paragraph in document.paragraphs if paragraph.text.startswith("本工程采用")
    )
    assert body.paragraph_format.first_line_indent.pt == 28

    section = document.sections[0]
    assert round(section.top_margin.cm, 1) == 2.0
    assert round(section.left_margin.cm, 1) == 2.2
    assert section.footer.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT
    footer_xml = section.footer.paragraphs[0]._p.xml
    assert "PAGE" in footer_xml
    assert "NUMPAGES" in footer_xml
    assert "页/共" in section.footer.paragraphs[0].text

    table_run = document.tables[0].cell(1, 1).paragraphs[0].runs[0]
    assert table_run.font.size.pt == 14
