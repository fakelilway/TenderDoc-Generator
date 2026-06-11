from services import generation_service
from utils.docx_exporter import combine_delivery_volumes


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


class _FakeCursor:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))


class _FakeConnection:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.statements)


class _FakeMinio:
    def __init__(self):
        self.uploads = []

    def upload_file(self, bucket, file_path, object_name):
        content = None
        if str(file_path).endswith(".md"):
            content = file_path.read_text(encoding="utf-8")
        self.uploads.append((bucket, object_name, content))
        return object_name


def test_export_markdown_for_project_stores_markdown_docx_and_quality(
    monkeypatch,
) -> None:
    statements = []
    fake_minio = _FakeMinio()
    monkeypatch.setattr(
        generation_service, "_connect", lambda: _FakeConnection(statements)
    )
    monkeypatch.setattr(generation_service, "minio_client", fake_minio)

    markdown = "# 项目\n\n## 施工组织设计\n\n这是完整生成段落，描述施工部署、质量、安全和进度。\n"
    quality_report = generation_service.evaluate_generation_quality(markdown)

    markdown_object, docx_object = generation_service.export_markdown_for_project(
        7,
        markdown,
        quality_report,
    )

    assert markdown_object == "projects/7/generated/bid.md"
    assert docx_object == "projects/7/generated/bid.docx"
    assert [upload[1] for upload in fake_minio.uploads] == [
        "projects/7/generated/bid.md",
        "projects/7/generated/bid.docx",
    ]
    assert any("generated_docx_path" in statement for statement, _params in statements)
    assert any(
        params and "generated" in params for _statement, params in statements
    )


def test_export_markdown_for_project_strips_meta_notes(monkeypatch) -> None:
    statements = []
    fake_minio = _FakeMinio()
    captured = {}

    def fake_markdown_to_docx(markdown, docx_path, **kwargs):
        captured["docx_markdown"] = markdown
        captured["title"] = kwargs.get("title")

    monkeypatch.setattr(
        generation_service, "_connect", lambda: _FakeConnection(statements)
    )
    monkeypatch.setattr(generation_service, "minio_client", fake_minio)
    monkeypatch.setattr(generation_service, "markdown_to_docx", fake_markdown_to_docx)

    markdown = combine_delivery_volumes(
        "测试项目投标文件",
        {
            "commercial": "# 商务文件\n\n法定代表人授权书等商务内容，满足资格审查要求。",
            "technical": "# 技术文件\n\n## 施工组织设计\n\n这是完整生成段落，描述施工部署、质量、安全和进度。",
            "pricing": "# 报价文件\n\n投标报价汇总表内容。",
        },
        notes="第 1 轮审查发现 2 处问题，已自动修正。",
    )
    markdown += "\n## 审查修正说明\n\n遗留的旧版审查说明段落。\n"

    generation_service.export_markdown_for_project(7, markdown, {"usable_rate": 1.0})

    uploaded_markdown = next(
        content
        for _bucket, object_name, content in fake_minio.uploads
        if object_name.endswith(".md")
    )
    for exported in (uploaded_markdown, captured["docx_markdown"]):
        assert "tdg:volume" not in exported
        assert "审查发现" not in exported
        assert "审查修正说明" not in exported
        assert "施工组织设计" in exported
        assert "投标报价汇总表内容" in exported
    assert captured["title"] == "测试项目投标文件"
