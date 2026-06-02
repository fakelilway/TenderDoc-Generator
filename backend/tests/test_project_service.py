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
