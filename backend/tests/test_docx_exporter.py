from pathlib import Path

from docx import Document

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
