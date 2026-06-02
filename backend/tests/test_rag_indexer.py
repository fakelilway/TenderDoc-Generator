from pathlib import Path

import pytest
from docx import Document

from rag.indexer import (
    index_document,
    index_knowledge_base,
    iter_knowledge_files,
    split_text,
)


def _write_docx(path: Path, text: str) -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(path)


def test_split_text_uses_overlap() -> None:
    chunks = split_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10, chunk_overlap=3)

    assert chunks == ["abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxyz"]


def test_iter_knowledge_files_filters_supported_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("skip", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_docx(nested / "b.docx", "docx text")

    files = iter_knowledge_files(tmp_path)

    assert [path.name for path in files] == ["a.txt", "b.docx"]


def test_index_document_extracts_metadata_and_chunks(tmp_path: Path) -> None:
    source = tmp_path / "方案.txt"
    source.write_text("施工组织设计\n" + "技术措施" * 80, encoding="utf-8")

    chunks = index_document(
        source, source_root=tmp_path, chunk_size=80, chunk_overlap=10
    )

    assert len(chunks) > 1
    assert chunks[0].content.startswith("施工组织设计")
    assert chunks[0].metadata == {
        "source_path": "方案.txt",
        "file_name": "方案.txt",
        "file_type": "txt",
        "chunk_index": 0,
    }


def test_index_knowledge_base_extracts_txt_docx_and_pdf(tmp_path: Path) -> None:
    (tmp_path / "资质.txt").write_text("企业资质：建筑工程施工总承包", encoding="utf-8")
    _write_docx(tmp_path / "业绩.docx", "类似工程业绩：高层住宅")
    fixture_pdf = Path(__file__).parent / "fixtures" / "tenders" / "1招标文件正文.pdf"
    pdf_copy = tmp_path / "招标.pdf"
    pdf_copy.write_bytes(fixture_pdf.read_bytes())

    chunks = index_knowledge_base(tmp_path, chunk_size=5000, chunk_overlap=200)
    sources = {chunk.metadata["source_path"] for chunk in chunks}

    assert {"资质.txt", "业绩.docx", "招标.pdf"} <= sources
    assert any("建筑工程施工总承包" in chunk.content for chunk in chunks)
    assert any("类似工程业绩" in chunk.content for chunk in chunks)
    assert any("投标人" in chunk.content or "招标" in chunk.content for chunk in chunks)


def test_split_text_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError, match="smaller"):
        split_text("hello", chunk_size=10, chunk_overlap=10)
