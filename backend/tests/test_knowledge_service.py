from services import knowledge_service


class FakeMinio:
    def __init__(self):
        self.uploads = []

    def upload_file(self, bucket, file_bytes, object_name):
        self.uploads.append((bucket, file_bytes, object_name))
        return object_name


def test_image_upload_defaults_to_structured_evidence_without_ocr(monkeypatch) -> None:
    stored = {}
    monkeypatch.setattr(knowledge_service, "minio_client", FakeMinio())
    monkeypatch.setattr(
        knowledge_service,
        "extract_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OCR skipped")),
    )
    monkeypatch.setattr(
        knowledge_service,
        "store_knowledge_chunks",
        lambda **kwargs: stored.update(kwargs) or {"document_id": 7, "chunk_ids": []},
    )

    result = knowledge_service.index_uploaded_knowledge(
        b"image-bytes",
        "人员_张三_身份证.jpg",
        content_type="image/jpeg",
        document_type="身份证",
    )

    assert result["document_id"] == 7
    assert result["chunk_ids"] == []
    assert result["indexing_status"] == "structured_evidence"
    assert stored["chunks"] == []
    assert stored["metadata"]["ingestion_mode"] == "structured_evidence"


def test_doc_upload_in_rag_mode_falls_back_to_evidence_only_when_conversion_missing(
    monkeypatch,
) -> None:
    stored = {}
    monkeypatch.setattr(knowledge_service, "minio_client", FakeMinio())
    monkeypatch.setattr(
        knowledge_service,
        "extract_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("Legacy .doc conversion requires LibreOffice/soffice.")
        ),
    )
    monkeypatch.setattr(
        knowledge_service,
        "store_knowledge_chunks",
        lambda **kwargs: stored.update(kwargs) or {"document_id": 8, "chunk_ids": []},
    )

    result = knowledge_service.index_uploaded_knowledge(
        b"doc-bytes",
        "历史投标文件.doc",
        content_type="application/msword",
        ingestion_mode="rag_text",
    )

    assert result["document_id"] == 8
    assert result["indexing_status"] == "evidence_only"
    assert "LibreOffice" in result["extraction_message"]
    assert stored["metadata"]["ingestion_mode"] == "evidence_only"
