import pytest

from schemas.tender import TenderRequirements
from services import project_service


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows.pop(0)

    def fetchall(self):
        rows = list(self.rows)
        self.rows = []
        return rows


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj


class FakeMinio:
    def __init__(self):
        self.uploads = []

    def upload_file(self, bucket, file_bytes, object_name):
        self.uploads.append((bucket, file_bytes, object_name))
        return object_name


def test_create_project_uploads_file_and_records_path(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            {
                "id": 42,
                "name": "项目",
                "tender_file_path": None,
                "parsed_json": None,
                "status": "uploading",
                "created_at": None,
            },
            {
                "id": 42,
                "name": "项目",
                "tender_file_path": "projects/42/tender/file.txt",
                "parsed_json": None,
                "status": "uploaded",
                "created_at": None,
            },
        ]
    )
    fake_minio = FakeMinio()

    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", fake_minio)
    monkeypatch.setattr(
        project_service,
        "_tender_object_name",
        lambda project_id, filename: f"projects/{project_id}/tender/file.txt",
    )

    project = project_service.create_project(
        "项目",
        b"tender text",
        "招标 文件.txt",
        "text/plain",
    )

    assert project["id"] == 42
    assert project["status"] == "uploaded"
    assert project["tender_file_path"] == "projects/42/tender/file.txt"
    assert fake_minio.uploads == [
        (
            project_service.settings.minio_bucket,
            b"tender text",
            "projects/42/tender/file.txt",
        )
    ]
    assert len(cursor.statements) == 3


def test_parse_project_downloads_parses_and_stores_json(monkeypatch) -> None:
    cursors = [
        FakeCursor(
            [
                {
                    "id": 42,
                    "name": "项目",
                    "tender_file_path": "projects/42/tender/file.txt",
                    "parsed_json": None,
                    "status": "uploaded",
                    "created_at": None,
                }
            ]
        ),
        FakeCursor(
            [
                {
                    "file_name": "file.txt",
                    "file_path": "projects/42/tender/file.txt",
                    "file_type": "text/plain",
                }
            ]
        ),
        FakeCursor(
            [
                {
                    "id": 42,
                    "name": "项目",
                    "tender_file_path": "projects/42/tender/file.txt",
                    "parsed_json": {
                        "project_name": "项目",
                        "qualification_list": [],
                        "technical_score_items": [],
                        "invalid_bid_items": [],
                    },
                    "status": "parsed",
                    "created_at": None,
                }
            ]
        ),
    ]

    class FakeDownloadMinio:
        def download_bytes(self, bucket, object_name):
            assert bucket == project_service.settings.minio_bucket
            assert object_name == "projects/42/tender/file.txt"
            return "项目名称：项目".encode("utf-8")

    def fake_connect():
        return FakeConnection(cursors.pop(0))

    monkeypatch.setattr(project_service, "_connect", fake_connect)
    monkeypatch.setattr(project_service, "minio_client", FakeDownloadMinio())
    monkeypatch.setattr(
        project_service,
        "parse_tender",
        lambda text: TenderRequirements(project_name="项目"),
    )

    project = project_service.parse_project(42)

    assert project["status"] == "parsed"
    assert project["parsed_json"]["project_name"] == "项目"
    assert not cursors


def test_create_project_records_owner_user_id(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            {
                "id": 9,
                "name": "项目",
                "tender_file_path": None,
                "parsed_json": None,
                "status": "uploading",
                "created_at": None,
            },
            {
                "id": 9,
                "name": "项目",
                "tender_file_path": "projects/9/tender/file.txt",
                "parsed_json": None,
                "status": "uploaded",
                "created_at": None,
            },
        ]
    )
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", FakeMinio())
    monkeypatch.setattr(
        project_service,
        "_tender_object_name",
        lambda project_id, filename: f"projects/{project_id}/tender/file.txt",
    )

    project_service.create_project(
        "项目", b"text", "file.txt", owner_user_id=5, template_id=3
    )

    insert_statement, insert_params = cursor.statements[0]
    assert "owner_user_id" in insert_statement
    assert "template_id" in insert_statement
    assert insert_params == ("项目", "uploading", 5, 3)


def test_authorize_project_access_allows_owner(monkeypatch) -> None:
    cursor = FakeCursor([{"owner_user_id": 5}])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))

    assert project_service.authorize_project_access(1, user_id=5) == 5


def test_authorize_project_access_rejects_other_user(monkeypatch) -> None:
    cursor = FakeCursor([{"owner_user_id": 5}])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))

    with pytest.raises(project_service.ProjectAccessError):
        project_service.authorize_project_access(1, user_id=99)


def test_authorize_project_access_allows_admin(monkeypatch) -> None:
    cursor = FakeCursor([{"owner_user_id": 5}])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))

    assert project_service.authorize_project_access(1, user_id=99, is_admin=True) == 5


def test_authorize_project_access_allows_legacy_unowned(monkeypatch) -> None:
    cursor = FakeCursor([{"owner_user_id": None}])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))

    assert project_service.authorize_project_access(1, user_id=99) is None


def test_authorize_project_access_missing_project(monkeypatch) -> None:
    cursor = FakeCursor([])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))

    with pytest.raises(project_service.ProjectNotFoundError):
        project_service.authorize_project_access(1, user_id=5)


def test_list_projects_for_regular_user_filters_owner(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            {
                "id": 2,
                "name": "项目B",
                "status": "approved",
                "created_at": None,
                "owner_user_id": 5,
                "generated_docx_path": "projects/2/generated/bid.docx",
                "workflow_state_json": {"status": "approved"},
                "owner_username": "alice",
                "owner_display_name": "爱丽丝",
            },
            {
                "id": 1,
                "name": "项目A",
                "status": "processing",
                "created_at": None,
                "owner_user_id": 5,
                "generated_docx_path": None,
                "workflow_state_json": None,
                "owner_username": "alice",
                "owner_display_name": "爱丽丝",
            },
        ]
    )
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))

    projects = project_service.list_projects(viewer_id=5, is_admin=False)

    statement, params = cursor.statements[0]
    assert "owner_user_id = %s OR p.owner_user_id IS NULL" in statement
    assert params[0] == 5
    assert [p["project_id"] for p in projects] == [2, 1]
    assert projects[0]["has_download"] is True
    assert projects[1]["has_download"] is False
    assert projects[0]["owner_username"] == "alice"


def test_list_projects_admin_can_filter_by_owner(monkeypatch) -> None:
    cursor = FakeCursor([])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))

    project_service.list_projects(viewer_id=1, is_admin=True, owner_user_id=7)

    statement, params = cursor.statements[0]
    assert "p.owner_user_id = %s" in statement
    assert params[0] == 7


class FakePresignMinio:
    def __init__(self):
        self.uploads = []
        self.presigned = []

    def upload_file(self, bucket, file_bytes, object_name):
        self.uploads.append((bucket, file_bytes, object_name))
        return object_name

    def get_presigned_url(self, bucket, object_name, expiry=3600, response_filename=None):
        self.presigned.append(
            {
                "bucket": bucket,
                "object_name": object_name,
                "expiry": expiry,
                "response_filename": response_filename,
            }
        )
        return f"https://minio.local/{object_name}?filename={response_filename}"


def _download_project_row(**overrides):
    row = {
        "id": 7,
        "name": "高层住宅项目",
        "tender_file_path": None,
        "parsed_json": None,
        "generated_markdown_path": "projects/7/generated/bid.md",
        "generated_docx_path": "projects/7/generated/bid.docx",
        "generation_quality_json": None,
        "review_report_json": None,
        "workflow_state_json": None,
        "confirmed_parsed_json": None,
        "bid_outline_json": None,
        "selected_chunk_ids": None,
        "edited_markdown": None,
        "final_checklist_json": None,
        "final_versions_json": [{"version": 1}, {"version": 2}],
        "pricing_strategy_json": None,
        "pricing_strategy_report_json": None,
        "score_prediction_json": None,
        "response_matrix_json": None,
        "status": "approved",
        "created_at": None,
    }
    row.update(overrides)
    return row


def test_download_url_docx_uses_versioned_filename(monkeypatch) -> None:
    cursor = FakeCursor([_download_project_row()])
    fake_minio = FakePresignMinio()
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", fake_minio)

    result = project_service.get_project_download_url(7, artifact="docx")

    assert result["artifact"] == "docx"
    assert result["filename"] == "高层住宅项目_v2.docx"
    assert fake_minio.presigned[0]["object_name"] == "projects/7/generated/bid.docx"
    assert fake_minio.presigned[0]["response_filename"] == "高层住宅项目_v2.docx"


def test_download_url_markdown_artifact(monkeypatch) -> None:
    cursor = FakeCursor([_download_project_row()])
    fake_minio = FakePresignMinio()
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", fake_minio)

    result = project_service.get_project_download_url(7, artifact="markdown")

    assert result["artifact"] == "markdown"
    assert result["filename"].endswith(".md")
    assert fake_minio.presigned[0]["object_name"] == "projects/7/generated/bid.md"


def test_download_url_review_artifact_builds_and_uploads_report(monkeypatch) -> None:
    cursor = FakeCursor(
        [
            _download_project_row(
                review_report_json={
                    "pass_count": 2,
                    "warning_count": 1,
                    "fail_count": 0,
                    "findings": [
                        {
                            "rule": "保证金",
                            "status": "pass",
                            "severity": "high",
                            "suggestion": "保持",
                            "evidence": "已响应保证金",
                        }
                    ],
                }
            )
        ]
    )
    fake_minio = FakePresignMinio()
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", fake_minio)

    result = project_service.get_project_download_url(7, artifact="review")

    assert result["artifact"] == "review"
    assert fake_minio.uploads, "review report should be uploaded to MinIO"
    bucket, payload, object_name = fake_minio.uploads[0]
    assert object_name == "projects/7/generated/review_report.md"
    assert b"\xe5\xae\xa1\xe6\x9f\xa5\xe6\x8a\xa5\xe5\x91\x8a" in payload  # "审查报告"
    assert fake_minio.presigned[0]["object_name"] == "projects/7/generated/review_report.md"


def test_download_url_review_without_report_raises(monkeypatch) -> None:
    cursor = FakeCursor([_download_project_row(review_report_json=None)])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", FakePresignMinio())

    with pytest.raises(ValueError):
        project_service.get_project_download_url(7, artifact="review")


def test_download_url_rejects_unknown_artifact(monkeypatch) -> None:
    cursor = FakeCursor([_download_project_row()])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", FakePresignMinio())

    with pytest.raises(ValueError):
        project_service.get_project_download_url(7, artifact="pdf")


class FakeDeleteMinio:
    def __init__(self):
        self.removed = []

    def remove_file(self, bucket, object_name):
        self.removed.append((bucket, object_name))


def test_delete_project_removes_objects_and_row(monkeypatch) -> None:
    cursor = FakeCursor([_download_project_row()])
    fake_minio = FakeDeleteMinio()
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", fake_minio)

    project_service.delete_project(7)

    removed_objects = [object_name for _bucket, object_name in fake_minio.removed]
    assert "projects/7/generated/bid.docx" in removed_objects
    assert "projects/7/generated/bid.md" in removed_objects
    delete_statements = [
        statement for statement, _params in cursor.statements if "DELETE FROM projects" in statement
    ]
    assert delete_statements, "project row should be deleted"


def test_delete_project_missing_raises(monkeypatch) -> None:
    cursor = FakeCursor([])
    monkeypatch.setattr(project_service, "_connect", lambda: FakeConnection(cursor))
    monkeypatch.setattr(project_service, "minio_client", FakeDeleteMinio())

    with pytest.raises(project_service.ProjectNotFoundError):
        project_service.delete_project(7)
