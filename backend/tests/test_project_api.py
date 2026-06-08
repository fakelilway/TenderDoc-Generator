import pytest
from fastapi.testclient import TestClient

from api.main import app, authorized_project
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
    # Project-scoped routes guard access through authorized_project; bypass the
    # database-backed ownership check by default so endpoint behaviour can be
    # tested in isolation.
    app.dependency_overrides[authorized_project] = lambda: 0
    yield
    app.dependency_overrides.clear()


def test_create_project_uploads_tender(monkeypatch) -> None:
    captured = {}

    def fake_create_project(
        name, file_bytes, filename, content_type=None, owner_user_id=None
    ):
        captured.update(
            name=name,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            owner_user_id=owner_user_id,
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
        "owner_user_id": 1,
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
    captured = {}

    def fake_download(project_id, artifact="docx", expiry=3600):
        captured.update(project_id=project_id, artifact=artifact, expiry=expiry)
        return {
            "project_id": project_id,
            "status": "generated",
            "download_url": "https://minio.local/projects/7/generated/bid.docx",
            "expires_in": expiry,
            "artifact": artifact,
            "artifact_label": "技术标 DOCX",
            "filename": "项目_v1.docx",
        }

    monkeypatch.setattr(
        "api.main.project_service.get_project_download_url", fake_download
    )

    response = client.get("/api/project/7/download")

    assert response.status_code == 200
    body = response.json()
    assert body["download_url"] == "https://minio.local/projects/7/generated/bid.docx"
    assert body["artifact"] == "docx"
    assert body["filename"] == "项目_v1.docx"
    assert captured == {"project_id": 7, "artifact": "docx", "expiry": 3600}


def test_download_project_supports_review_artifact(monkeypatch) -> None:
    captured = {}

    def fake_download(project_id, artifact="docx", expiry=3600):
        captured.update(artifact=artifact, expiry=expiry)
        return {
            "project_id": project_id,
            "status": "approved",
            "download_url": "https://minio.local/projects/7/generated/review_report.md",
            "expires_in": expiry,
            "artifact": artifact,
            "artifact_label": "审查报告",
            "filename": "项目_审查报告_v1.md",
        }

    monkeypatch.setattr(
        "api.main.project_service.get_project_download_url", fake_download
    )

    response = client.get(
        "/api/project/7/download", params={"artifact": "review", "expiry": 600}
    )

    assert response.status_code == 200
    assert response.json()["artifact_label"] == "审查报告"
    assert captured == {"artifact": "review", "expiry": 600}


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


def test_confirm_parsed_result_endpoint(monkeypatch) -> None:
    parsed_json = {
        "project_name": "人工确认项目",
        "qualification_list": [],
        "technical_score_items": [],
        "invalid_bid_items": [],
    }
    captured = {}

    def fake_confirm(project_id, payload):
        captured["project_id"] = project_id
        captured["payload"] = payload
        return {
            "id": project_id,
            "status": "parsed_confirmed",
            "confirmed_parsed_json": payload,
        }

    monkeypatch.setattr(
        "api.main.project_service.confirm_parsed_result",
        fake_confirm,
    )

    response = client.patch("/api/project/7/parsed", json={"parsed_json": parsed_json})

    assert response.status_code == 200
    assert response.json()["status"] == "parsed_confirmed"
    assert captured == {"project_id": 7, "payload": parsed_json}


def test_build_and_save_outline_endpoints(monkeypatch) -> None:
    outline = [
        {
            "title": "第一章、总体施工组织布置及规划",
            "required": True,
            "source_item": "",
            "focus_points": ["施工部署"],
        }
    ]
    monkeypatch.setattr(
        "api.main.project_service.build_project_outline",
        lambda project_id: {
            "id": project_id,
            "status": "outline_ready",
            "bid_outline_json": outline,
        },
    )
    saved = {}

    def fake_save(project_id, payload):
        saved["project_id"] = project_id
        saved["outline"] = payload
        return {
            "id": project_id,
            "status": "outline_confirmed",
            "bid_outline_json": payload,
        }

    monkeypatch.setattr("api.main.project_service.save_project_outline", fake_save)

    build_response = client.post("/api/project/7/outline")
    save_response = client.patch("/api/project/7/outline", json={"outline": outline})

    assert build_response.status_code == 200
    assert build_response.json()["status"] == "outline_ready"
    assert save_response.status_code == 200
    assert save_response.json()["status"] == "outline_confirmed"
    assert saved == {"project_id": 7, "outline": outline}


def test_save_knowledge_selection_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.save_selected_knowledge_chunks",
        lambda project_id, selected_chunk_ids: {
            "project_id": project_id,
            "selected_chunk_ids": selected_chunk_ids,
            "references": [{"chunk_id": selected_chunk_ids[0], "title": "模板"}],
        },
    )

    response = client.patch(
        "/api/project/7/knowledge-selection",
        json={"selected_chunk_ids": [101]},
    )

    assert response.status_code == 200
    assert response.json()["references"][0]["title"] == "模板"


def test_save_draft_and_final_checklist_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.save_draft_markdown",
        lambda project_id, markdown: {
            "id": project_id,
            "status": "draft_saved",
            "edited_markdown": markdown,
            "review_report_json": {"fail_count": 0, "findings": []},
        },
    )
    monkeypatch.setattr(
        "api.main.project_service.build_final_checklist",
        lambda project_id: {
            "project_id": project_id,
            "checklist": {"manual_confirmation_points": []},
            "versions": [{"version": 1}],
        },
    )

    draft_response = client.patch(
        "/api/project/7/draft",
        json={"markdown": "# 标书\n\n人工确认点：【待补充】报价"},
    )
    checklist_response = client.get("/api/project/7/final-checklist")

    assert draft_response.status_code == 200
    assert draft_response.json()["status"] == "draft_saved"
    assert checklist_response.status_code == 200
    assert checklist_response.json()["versions"][0]["version"] == 1


def test_strategy_score_and_matrix_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.project_service.build_project_pricing_strategy",
        lambda project_id: {
            "project_id": project_id,
            "pricing_strategy": {
                "project_name": "阶段8项目",
                "project_scale": "人工确认",
                "schedule_risk": "medium",
                "payment_terms": [],
                "competition_intensity": "人工确认",
                "quote_risk": "medium",
                "guarantee_requirements": [],
                "manual_fields": [
                    {
                        "label": "投标总价",
                        "reason": "人工填写",
                        "source_text": "",
                        "required": True,
                    }
                ],
                "extracted_conditions": [],
            },
            "pricing_report": {
                "project_name": "阶段8项目",
                "strategy_suggestions": ["不自动报价"],
                "risk_warnings": [],
                "commercial_response_notes": [],
                "manual_confirmation_points": ["人工确认点：【待补充】投标总价"],
                "prohibited_auto_pricing": True,
            },
        },
    )
    monkeypatch.setattr(
        "api.main.project_service.build_project_score_prediction",
        lambda project_id: {
            "project_id": project_id,
            "score_prediction": {
                "project_name": "阶段8项目",
                "total_max_score": 100,
                "predicted_total_score": 78,
                "score_rate": 0.78,
                "win_probability": 0.56,
                "win_probability_rationale": "覆盖率估算",
                "uncertainty_notes": ["非真实评标结果"],
                "strengths": [],
                "weaknesses": [],
                "items": [],
            },
        },
    )
    monkeypatch.setattr(
        "api.main.project_service.build_project_response_matrix",
        lambda project_id: {
            "project_id": project_id,
            "response_matrix": {
                "project_id": project_id,
                "rows": [
                    {
                        "requirement_type": "invalid_bid_item",
                        "requirement_title": "保证金",
                        "requirement_text": "未提交保证金否决投标",
                        "response_status": "found",
                        "response_location": {
                            "line_number": 3,
                            "paragraph_index": 1,
                            "snippet": "保证金响应",
                        },
                        "response_section": "商务响应",
                        "review_status": "pass",
                        "manual_confirmation_required": True,
                        "manual_confirmation_note": "人工核对",
                    }
                ],
                "invalid_bid_coverage_count": 1,
                "total_invalid_bid_count": 1,
            },
        },
    )

    pricing_response = client.post("/api/project/7/pricing-strategy")
    score_response = client.post("/api/project/7/score-prediction")
    matrix_response = client.post("/api/project/7/response-matrix")

    assert pricing_response.status_code == 200
    assert pricing_response.json()["pricing_report"]["prohibited_auto_pricing"] is True
    assert score_response.status_code == 200
    assert score_response.json()["score_prediction"]["win_probability"] == 0.56
    assert matrix_response.status_code == 200
    assert matrix_response.json()["response_matrix"]["rows"][0]["response_section"] == "商务响应"


def test_list_projects_returns_user_projects(monkeypatch) -> None:
    captured = {}

    def fake_list_projects(viewer_id, is_admin, owner_user_id, limit, offset):
        captured.update(
            viewer_id=viewer_id,
            is_admin=is_admin,
            owner_user_id=owner_user_id,
            limit=limit,
            offset=offset,
        )
        return [
            {
                "project_id": 1,
                "name": "项目A",
                "status": "approved",
                "created_at": None,
                "owner_user_id": 1,
                "owner_username": "admin",
                "owner_display_name": "管理员",
                "has_download": True,
            }
        ]

    monkeypatch.setattr("api.main.project_service.list_projects", fake_list_projects)

    response = client.get("/api/projects")

    assert response.status_code == 200
    body = response.json()
    assert body["projects"][0]["project_id"] == 1
    assert body["projects"][0]["has_download"] is True
    assert captured["viewer_id"] == 1
    assert captured["is_admin"] is True


def test_project_access_forbidden_for_non_owner(monkeypatch) -> None:
    app.dependency_overrides[auth_service.get_current_user] = lambda: UserProfile(
        id=2,
        username="bob",
        display_name="Bob",
        role="user",
        can_view_knowledge=False,
        can_edit_knowledge=False,
    )
    # Exercise the real ownership dependency instead of the test bypass.
    app.dependency_overrides.pop(authorized_project, None)
    monkeypatch.setattr(
        "api.main.project_service.get_project_owner", lambda project_id: 5
    )
    monkeypatch.setattr(
        "api.main.project_service.get_project_status",
        lambda project_id: {"project_id": project_id, "status": "parsed", "parsed": True},
    )

    response = client.get("/api/project/7/status")

    assert response.status_code == 403


def test_project_access_allowed_for_owner(monkeypatch) -> None:
    app.dependency_overrides[auth_service.get_current_user] = lambda: UserProfile(
        id=5,
        username="alice",
        display_name="Alice",
        role="user",
        can_view_knowledge=False,
        can_edit_knowledge=False,
    )
    app.dependency_overrides.pop(authorized_project, None)
    monkeypatch.setattr(
        "api.main.project_service.get_project_owner", lambda project_id: 5
    )
    monkeypatch.setattr(
        "api.main.project_service.get_project_status",
        lambda project_id: {"project_id": project_id, "status": "parsed", "parsed": True},
    )

    response = client.get("/api/project/7/status")

    assert response.status_code == 200
    assert response.json()["status"] == "parsed"


def test_delete_project_returns_ok(monkeypatch) -> None:
    captured = {}

    def fake_delete(project_id):
        captured["project_id"] = project_id

    monkeypatch.setattr("api.main.project_service.delete_project", fake_delete)

    response = client.delete("/api/project/7")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured == {"project_id": 7}
