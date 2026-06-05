import pytest
from fastapi.testclient import TestClient

from api.main import app
from rag import retriever
from schemas.auth import UserAdminProfile, UserProfile
from schemas.workflow import WorkflowState
from services import auth_service
from services.project_service import ProjectNotFoundError


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_user():
    app.dependency_overrides[auth_service.get_current_user] = lambda: UserProfile(
        id=1,
        username="admin",
        display_name="管理员",
        role="admin",
        can_view_knowledge=True,
        can_edit_knowledge=True,
    )
    yield
    app.dependency_overrides.clear()


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


def test_list_knowledge_documents_returns_indexed_files(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.knowledge_service.list_knowledge_documents",
        lambda limit=50: [
            {
                "document_id": 9,
                "file_name": "企业技术标模板.pdf",
                "file_path": "knowledge/template.pdf",
                "file_type": "pdf",
                "chunk_count": 12,
                "created_at": "2026-06-04T10:00:00+08:00",
            }
        ],
    )

    response = client.get("/api/knowledge/documents")

    assert response.status_code == 200
    assert response.json()["documents"][0]["file_name"] == "企业技术标模板.pdf"
    assert response.json()["documents"][0]["chunk_count"] == 12


def test_knowledge_requires_view_permission() -> None:
    app.dependency_overrides[auth_service.get_current_user] = lambda: UserProfile(
        id=2,
        username="viewer",
        display_name="普通用户",
        role="user",
        can_view_knowledge=False,
        can_edit_knowledge=False,
    )

    response = client.get("/api/knowledge/documents")

    assert response.status_code == 403


def test_rename_knowledge_document_updates_title(monkeypatch) -> None:
    captured = {}

    def fake_rename(document_id, title):
        captured["document_id"] = document_id
        captured["title"] = title
        return {
            "document_id": document_id,
            "file_name": title,
            "file_path": "knowledge/template.pdf",
            "file_type": "pdf",
            "chunk_count": 12,
            "created_at": "2026-06-04T10:00:00+08:00",
        }

    monkeypatch.setattr(
        "api.main.knowledge_service.rename_knowledge_document",
        fake_rename,
    )

    response = client.patch(
        "/api/knowledge/documents/9",
        json={"title": "企业技术标模板 v2"},
    )

    assert response.status_code == 200
    assert response.json()["file_name"] == "企业技术标模板 v2"
    assert captured == {"document_id": 9, "title": "企业技术标模板 v2"}


def test_delete_knowledge_document_removes_document(monkeypatch) -> None:
    captured = {}

    def fake_delete(document_id):
        captured["document_id"] = document_id

    monkeypatch.setattr(
        "api.main.knowledge_service.delete_knowledge_document",
        fake_delete,
    )

    response = client.delete("/api/knowledge/documents/9")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured == {"document_id": 9}


def test_admin_can_list_create_update_delete_users_and_generate_codes(monkeypatch) -> None:
    users = [
        UserAdminProfile(
            id=1,
            username="admin",
            display_name="管理员",
            role="admin",
            can_view_knowledge=True,
            can_edit_knowledge=True,
            is_active=True,
        )
    ]
    created = UserAdminProfile(
        id=2,
        username="demo",
        display_name="演示用户",
        role="user",
        can_view_knowledge=False,
        can_edit_knowledge=False,
        is_active=True,
    )
    updated = created.model_copy(
        update={"can_view_knowledge": True, "can_edit_knowledge": True}
    )
    monkeypatch.setattr("api.main.auth_service.list_users", lambda: users)
    monkeypatch.setattr("api.main.auth_service.create_user", lambda request: created)
    monkeypatch.setattr(
        "api.main.auth_service.create_registration_code",
        lambda admin_user_id: {
            "code": "ABCD-2345",
            "expires_at": "2026-06-05T10:00:00+08:00",
        },
    )
    monkeypatch.setattr(
        "api.main.auth_service.update_user_permissions",
        lambda user_id, request: updated,
    )
    deleted = {}
    monkeypatch.setattr(
        "api.main.auth_service.delete_user",
        lambda user_id: deleted.update(user_id=user_id),
    )

    list_response = client.get("/api/admin/users")
    code_response = client.post("/api/admin/registration-codes")
    create_response = client.post(
        "/api/admin/users",
        json={
            "username": "demo",
            "password": "secret1",
            "display_name": "演示用户",
            "can_view_knowledge": False,
            "can_edit_knowledge": False,
        },
    )
    update_response = client.patch(
        "/api/admin/users/2/permissions",
        json={
            "display_name": "演示用户",
            "is_active": True,
            "can_view_knowledge": True,
            "can_edit_knowledge": True,
        },
    )
    delete_response = client.delete("/api/admin/users/2")

    assert list_response.status_code == 200
    assert list_response.json()["users"][0]["role"] == "admin"
    assert code_response.status_code == 200
    assert code_response.json()["code"] == "ABCD-2345"
    assert create_response.status_code == 200
    assert create_response.json()["user"]["username"] == "demo"
    assert update_response.status_code == 200
    assert update_response.json()["user"]["can_edit_knowledge"] is True
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True}
    assert deleted == {"user_id": 2}


def test_run_project_workflow_starts_background_task(monkeypatch) -> None:
    captured = {}

    def fake_start(project_id, background_tasks):
        captured["project_id"] = project_id
        captured["background_tasks"] = background_tasks
        return {
            "project_id": project_id,
            "task_id": "workflow-task-123",
            "status": "processing",
            "awaiting_human": False,
            "iteration_count": 0,
            "review_report": None,
        }

    monkeypatch.setattr(
        "api.main.workflow_service.start_bid_workflow",
        fake_start,
    )

    response = client.post("/api/project/7/workflow/run")

    assert response.status_code == 200
    assert response.json() == {
        "project_id": 7,
        "status": "processing",
        "awaiting_human": False,
        "iteration_count": 0,
        "review_report": None,
    }
    assert captured["project_id"] == 7


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
