from docx import Document

from services.generation_service import _append_docx


def test_append_docx_merges_paragraphs_and_tables(tmp_path) -> None:
    """技术卷末尾拼附表:正文 + 附表段落/表格都在,表格存活。"""
    base = tmp_path / "technical.docx"
    appendix = tmp_path / "appendix.docx"

    b = Document()
    b.add_paragraph("施工组织设计正文")
    b.save(str(base))

    a = Document()
    a.add_paragraph("附表一 施工总体计划表")
    a.add_table(rows=3, cols=4)
    a.save(str(appendix))

    _append_docx(base, str(appendix))

    merged = Document(str(base))
    texts = [p.text for p in merged.paragraphs if p.text.strip()]
    assert "施工组织设计正文" in texts
    assert "附表一 施工总体计划表" in texts
    assert len(merged.tables) == 1  # 附表的真表格被保留
