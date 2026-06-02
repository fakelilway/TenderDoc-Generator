from pathlib import Path

from docx import Document

from utils.docx_exporter import markdown_to_docx


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
