from fastapi.testclient import TestClient

from api.main import app
from rag import retriever
from schemas.workflow import WorkflowState
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


def test_generate_project_starts_async_task(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.generation_service.start_generation",
        lambda project_id, background_tasks: {
            "task_id": "task-123",
            "status": "processing",
        },
    )

    response = client.post("/api/project/7/generate")

    assert response.status_code == 200
    assert response.json() == {
        "project_id": 7,
        "status": "processing",
        "task_id": "task-123",
    }


def test_download_project_returns_presigned_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.get_project_download_url",
        lambda project_id: {
            "project_id": project_id,
            "status": "generated",
            "download_url": "https://minio.local/projects/7/generated/bid.docx",
            "expires_in": 3600,
        },
    )

    response = client.get("/api/project/7/download")

    assert response.status_code == 200
    assert response.json() == {
        "project_id": 7,
        "status": "generated",
        "download_url": "https://minio.local/projects/7/generated/bid.docx",
        "expires_in": 3600,
    }


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


def test_upload_knowledge_indexes_file(monkeypatch) -> None:
    captured = {}

    def fake_index_uploaded_knowledge(file_bytes, filename, content_type=None):
        captured.update(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
        )
        return {
            "document_id": 9,
            "chunk_ids": [101, 102],
            "file_path": "knowledge/sample.txt",
        }

    monkeypatch.setattr(
        "api.main.knowledge_service.index_uploaded_knowledge",
        fake_index_uploaded_knowledge,
    )

    response = client.post(
        "/api/knowledge/upload",
        files={"file": ("sample.txt", b"knowledge text", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": 9,
        "chunk_ids": [101, 102],
        "file_path": "knowledge/sample.txt",
    }
    assert captured == {
        "file_bytes": b"knowledge text",
        "filename": "sample.txt",
        "content_type": "text/plain",
    }


def test_search_knowledge_returns_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.retriever.retrieve",
        lambda query, top_k: [
            retriever.RetrievalResult(
                chunk_id=1,
                document_id=2,
                content="高层住宅施工组织设计",
                metadata={"source_path": "a.txt"},
                distance=0.1,
                score=0.9,
            )
        ],
    )

    response = client.get(
        "/api/knowledge/search",
        params={"query": "高层住宅", "top_k": 1},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["content"] == "高层住宅施工组织设计"


def test_run_project_workflow_returns_human_review_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.workflow_service.run_bid_workflow",
        lambda project_id: WorkflowState(
            project_id=project_id,
            status="human_review",
            awaiting_human=True,
            iteration_count=1,
            review_report={"fail_count": 0, "findings": []},
        ),
    )

    response = client.post("/api/project/7/workflow/run")

    assert response.status_code == 200
    assert response.json()["status"] == "human_review"
    assert response.json()["awaiting_human"] is True


def test_confirm_project_approves_workflow(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.workflow_service.confirm_project",
        lambda project_id, approved, corrections=None: WorkflowState(
            project_id=project_id,
            status="approved",
            approved=approved,
            review_report={"fail_count": 0, "findings": []},
        ),
    )

    response = client.post(
        "/api/project/7/confirm",
        json={"approved": True, "corrections": {"note": "确认"}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["approved"] is True


def test_project_review_report_returns_workflow_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.get_project_review_report",
        lambda project_id: {
            "project_id": project_id,
            "status": "approved",
            "review_report": {"fail_count": 0},
            "workflow_state": {"status": "approved"},
        },
    )

    response = client.get("/api/project/7/review-report")

    assert response.status_code == 200
    assert response.json()["review_report"]["fail_count"] == 0
