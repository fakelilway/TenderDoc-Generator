from services import generation_service
from services.original_docx_format_service import PDF_PAGE_MARKER_PREFIX
from utils.docx_exporter import combine_delivery_volumes
from docx import Document


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
    assert any(params and "generated" in params for _statement, params in statements)


def test_export_markdown_for_project_prefers_original_docx_format(
    monkeypatch,
) -> None:
    statements = []
    fake_minio = _FakeMinio()
    fake_minio.download_bytes = lambda bucket, object_name: b"docx bytes"
    captured = {}

    def fake_build_original_format_docx(tender_bytes, output_path, *, profile=None):
        captured["tender_bytes"] = tender_bytes
        captured["profile"] = profile
        output_path.write_bytes(b"original format docx")

    def fail_markdown_to_docx(*args, **kwargs):
        raise AssertionError(
            "markdown_to_docx should not be used for original DOCX tender"
        )

    monkeypatch.setattr(
        generation_service, "_connect", lambda: _FakeConnection(statements)
    )
    monkeypatch.setattr(generation_service, "minio_client", fake_minio)
    monkeypatch.setattr(
        generation_service,
        "_fetch_tender_document",
        lambda project_id: {
            "file_name": "招标文件.docx",
            "file_path": "projects/7/tender/original.docx",
            "name": "测试项目",
            "confirmed_parsed_json": {"project_name": "测试项目", "tenderer_name": "招标人"},
            "parsed_json": None,
        },
    )
    monkeypatch.setattr(
        generation_service,
        "build_original_format_docx",
        fake_build_original_format_docx,
    )
    monkeypatch.setattr(generation_service, "markdown_to_docx", fail_markdown_to_docx)
    monkeypatch.setattr(
        generation_service,
        "get_company_profile",
        lambda: {"profile": {"company_name": "安徽正奇建设有限公司"}},
    )

    generation_service.export_markdown_for_project(7, "# 项目\n", {"usable_rate": 1.0})

    assert captured["tender_bytes"] == b"docx bytes"
    assert captured["profile"]["company_name"] == "安徽正奇建设有限公司"
    assert fake_minio.uploads[-1][1] == "projects/7/generated/bid.docx"


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


def test_split_original_pdf_docx_keeps_page_blocks_and_technical_only(tmp_path) -> None:
    source_path = tmp_path / "format.docx"
    source = Document()
    source.add_paragraph(f"{PDF_PAGE_MARKER_PREFIX}:0:投标文件（商务文件）目录")
    source.add_paragraph("商务页图层：投标函、授权委托书")
    source.add_paragraph(f"{PDF_PAGE_MARKER_PREFIX}:1:投标文件（技术文件）施工组织设计")
    source.add_paragraph("技术页图层：施工组织设计")
    source.add_paragraph(f"{PDF_PAGE_MARKER_PREFIX}:2:投标文件（报价文件）已标价工程量清单")
    source.add_paragraph("报价页图层：已标价工程量清单")
    source.save(source_path)

    markdown = combine_delivery_volumes(
        "测试项目",
        {
            "commercial": "# 商务文件\n\n商务正文不应追加到技术卷。",
            "technical": "# 技术文件\n\n施工组织正文应追加到技术卷。",
            "pricing": "# 报价文件\n\n报价正文不应追加到技术卷。",
        },
    )

    generation_service._split_and_export_volumes(source_path, tmp_path, 7, markdown)

    commercial = "\n".join(
        p.text for p in Document(tmp_path / "project_7_commercial.docx").paragraphs
    )
    technical = "\n".join(
        p.text for p in Document(tmp_path / "project_7_technical.docx").paragraphs
    )
    pricing = "\n".join(
        p.text for p in Document(tmp_path / "project_7_pricing.docx").paragraphs
    )

    assert "商务页图层" in commercial
    assert "技术页图层" not in commercial
    assert "技术页图层" in technical
    assert "施工组织正文应追加到技术卷" in technical
    assert "商务正文不应追加到技术卷" not in technical
    assert "报价正文不应追加到技术卷" not in technical
    assert "报价页图层" in pricing
