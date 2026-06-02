from fastapi.testclient import TestClient

from api.main import app
from services.project_service import ProjectNotFoundError


client = TestClient(app)


def test_create_project_uploads_tender(monkeypatch) -> None:
    captured = {}

    def fake_create_project(name, file_bytes, filename, content_type=None):
        captured.update(
            name=name,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
        )
        return {
            "id": 7,
            "status": "uploaded",
            "tender_file_path": "projects/7/tender/sample.txt",
        }

    monkeypatch.setattr("api.main.project_service.create_project", fake_create_project)

    response = client.post(
        "/api/project/create",
        data={"name": "测试项目"},
        files={"tender_file": ("sample.txt", b"hello tender", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": 7,
        "status": "uploaded",
        "tender_file_path": "projects/7/tender/sample.txt",
    }
    assert captured == {
        "name": "测试项目",
        "file_bytes": b"hello tender",
        "filename": "sample.txt",
        "content_type": "text/plain",
    }


def test_status_returns_parsed_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.get_project_status",
        lambda project_id: {
            "project_id": project_id,
            "status": "parsed",
            "parsed": True,
        },
    )

    response = client.get("/api/project/7/status")

    assert response.status_code == 200
    assert response.json() == {"project_id": 7, "status": "parsed", "parsed": True}


def test_parse_project_returns_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.parse_project",
        lambda project_id: {
            "id": project_id,
            "status": "parsed",
            "parsed_json": {
                "project_name": "测试项目",
                "qualification_list": [],
                "technical_score_items": [],
                "invalid_bid_items": [],
            },
        },
    )

    response = client.post("/api/project/7/parse")

    assert response.status_code == 200
    assert response.json()["parsed_json"]["project_name"] == "测试项目"


def test_generate_project_is_mvp_parse_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.parse_project",
        lambda project_id: {
            "id": project_id,
            "status": "parsed",
            "parsed_json": {"invalid_bid_items": []},
        },
    )

    response = client.post("/api/project/7/generate")

    assert response.status_code == 200
    assert response.json()["status"] == "parsed"


def test_review_returns_invalid_bid_items(monkeypatch) -> None:
    item = {
        "title": "否决投标",
        "description": "未提交保证金",
        "source": {"source_text": "未提交保证金", "page_number": 5},
    }
    monkeypatch.setattr(
        "api.main.project_service.get_project_review",
        lambda project_id: {
            "project_id": project_id,
            "status": "parsed",
            "invalid_bid_items": [item],
        },
    )

    response = client.get("/api/project/7/review")

    assert response.status_code == 200
    assert response.json()["invalid_bid_items"] == [item]


def test_project_not_found_returns_404(monkeypatch) -> None:
    def missing(_project_id):
        raise ProjectNotFoundError("Project 404 was not found")

    monkeypatch.setattr("api.main.project_service.get_project_status", missing)

    response = client.get("/api/project/404/status")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project 404 was not found"
