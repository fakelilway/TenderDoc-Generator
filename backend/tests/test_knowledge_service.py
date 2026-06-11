from services import knowledge_service


class FakeMinio:
    def __init__(self):
        self.uploads = []
        self.urls = []

    def upload_file(self, bucket, file_bytes, object_name):
        self.uploads.append((bucket, file_bytes, object_name))
        return object_name

    def get_presigned_url(
        self, bucket, object_name, expiry=3600, response_filename=None
    ):
        self.urls.append((bucket, object_name, expiry, response_filename))
        suffix = f"&download={response_filename}" if response_filename else ""
        return f"https://minio.local/{object_name}?expiry={expiry}{suffix}"


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


def test_preview_image_document_returns_view_and_download_urls(monkeypatch) -> None:
    fake_minio = FakeMinio()
    monkeypatch.setattr(knowledge_service, "minio_client", fake_minio)
    monkeypatch.setattr(
        knowledge_service,
        "_fetch_knowledge_document_row",
        lambda document_id: {
            "document_id": document_id,
            "file_name": "人员_张三_身份证.jpg",
            "file_path": "knowledge/id-card.jpg",
            "file_type": "image/jpeg",
            "metadata_json": {"indexing_status": "structured_evidence"},
        },
    )
    monkeypatch.setattr(knowledge_service, "_joined_chunk_text", lambda document_id: "")

    preview = knowledge_service.get_knowledge_document_preview(11)

    assert preview["document_id"] == 11
    assert preview["preview_type"] == "image"
    assert preview["content"] == ""
    assert (
        preview["preview_url"] == "https://minio.local/knowledge/id-card.jpg?expiry=900"
    )
    assert (
        preview["download_url"]
        == "https://minio.local/knowledge/id-card.jpg?expiry=900&download=人员_张三_身份证.jpg"
    )
    assert fake_minio.urls[-1][3] == "人员_张三_身份证.jpg"


def test_preview_text_document_returns_indexed_chunk_content(monkeypatch) -> None:
    monkeypatch.setattr(knowledge_service, "minio_client", FakeMinio())
    monkeypatch.setattr(
        knowledge_service,
        "_fetch_knowledge_document_row",
        lambda document_id: {
            "document_id": document_id,
            "file_name": "施工方案.txt",
            "file_path": "knowledge/plan.txt",
            "file_type": "text/plain",
            "metadata_json": {"indexing_status": "indexed"},
        },
    )
    monkeypatch.setattr(
        knowledge_service,
        "_joined_chunk_text",
        lambda document_id: "第一章 编制说明\n\n第二章 施工部署",
    )

    preview = knowledge_service.get_knowledge_document_preview(12)

    assert preview["preview_type"] == "text"
    assert preview["content"] == "第一章 编制说明\n\n第二章 施工部署"
    assert preview["indexing_status"] == "indexed"


def test_list_knowledge_image_references_prioritizes_matching_image_docs(
    monkeypatch,
) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            self.statement = statement

        def fetchall(self):
            return [
                (
                    1,
                    "人员_王兴祥_一级建造师证_公路工程.jpg",
                    "knowledge/builder.jpg",
                    "jpg",
                    {
                        "document_type": "人员",
                        "specialty": "公路工程",
                        "tags": ["一级建造师证"],
                    },
                ),
                (
                    2,
                    "历史投标文件.docx",
                    "knowledge/bid.docx",
                    "docx",
                    {"tags": ["历史标书"]},
                ),
                (
                    3,
                    "公司_营业执照.png",
                    "knowledge/license.png",
                    "png",
                    {"document_type": "公司", "tags": ["营业执照"]},
                ),
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(knowledge_service, "_connect", lambda: FakeConnection())

    references = knowledge_service.list_knowledge_image_references(
        "项目经理 一级建造师 公路工程",
        limit=2,
    )

    assert [reference["document_id"] for reference in references] == [1, 3]
    assert references[0]["caption"] == "人员 / 公路工程 / 一级建造师证"
