from services import generation_service


def test_evaluate_generation_quality_counts_placeholders() -> None:
    markdown = """# 标书

## 施工组织设计

这是一个完整段落，说明施工部署、进度安排、质量控制和安全文明施工措施。

待补充
"""

    report = generation_service.evaluate_generation_quality(markdown)

    assert report["total_paragraphs"] == 2
    assert report["needs_revision_paragraphs"] == 1
    assert report["usable_rate"] == 0.5


def test_generate_and_export_stores_markdown_docx_and_quality(monkeypatch) -> None:
    statements = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement, params=None):
            statements.append((statement, params))

        def fetchone(self):
            return {
                "id": 7,
                "name": "项目",
                "parsed_json": {
                    "project_name": "项目",
                    "qualification_list": [],
                    "technical_score_items": [
                        {
                            "title": "施工组织设计",
                            "description": "施工组织设计 30 分",
                            "source": {"source_text": "", "page_number": None},
                        }
                    ],
                    "invalid_bid_items": [],
                },
            }

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self, *args, **kwargs):
            return FakeCursor()

    class FakeMinio:
        def __init__(self):
            self.uploads = []

        def upload_file(self, bucket, file_path, object_name):
            self.uploads.append((bucket, str(file_path), object_name))
            return object_name

    fake_minio = FakeMinio()
    monkeypatch.setattr(generation_service, "_connect", lambda: FakeConnection())
    monkeypatch.setattr(generation_service, "minio_client", fake_minio)
    monkeypatch.setattr(
        generation_service.retriever,
        "retrieve",
        lambda query, top_k=3: ["高层住宅施工组织设计知识片段"],
    )
    monkeypatch.setattr(
        generation_service,
        "generate_bid_document",
        lambda requirements, chunks, bid_template=None: "# 项目\n\n## 施工组织设计\n\n这是完整生成段落，描述施工部署、质量、安全和进度。",
    )

    result = generation_service.generate_and_export(7)

    assert result.generated_markdown_path == "projects/7/generated/bid.md"
    assert result.generated_docx_path == "projects/7/generated/bid.docx"
    assert result.quality_report["usable_rate"] == 1.0
    assert [upload[2] for upload in fake_minio.uploads] == [
        "projects/7/generated/bid.md",
        "projects/7/generated/bid.docx",
    ]
    assert any("generated_docx_path" in statement for statement, _params in statements)
