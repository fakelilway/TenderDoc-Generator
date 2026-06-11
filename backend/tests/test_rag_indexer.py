from pathlib import Path

import pytest

from rag.indexer import index_document, split_text


def test_split_text_uses_overlap() -> None:
    chunks = split_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10, chunk_overlap=3)

    assert chunks == ["abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxyz"]


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


def test_split_text_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError, match="smaller"):
        split_text("hello", chunk_size=10, chunk_overlap=10)
