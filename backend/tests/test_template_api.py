import pytest
from fastapi.testclient import TestClient

from api.main import app, authorized_project
from schemas.auth import UserProfile
from services import auth_service

client = TestClient(app)


def _admin() -> UserProfile:
    return UserProfile(
        id=1,
        username="admin",
        display_name="管理员",
        role="admin",
        can_view_knowledge=True,
        can_edit_knowledge=True,
    )


def _normal_user() -> UserProfile:
    return UserProfile(
        id=2,
        username="bob",
        display_name="Bob",
        role="user",
        can_view_knowledge=True,
        can_edit_knowledge=False,
    )


@pytest.fixture(autouse=True)
def admin_user():
    app.dependency_overrides[auth_service.get_current_user] = _admin
    app.dependency_overrides[authorized_project] = lambda: 0
    yield
    app.dependency_overrides.clear()


def _template_summary(**overrides):
    summary = {
        "id": 1,
        "name": "公路模板",
        "source_filename": "road.pdf",
        "project_type": "公路工程",
        "specialty": "道路",
        "envelope_type": "第一信封",
        "region": "安徽",
        "project_year": 2025,
        "tags": ["公路"],
        "project_name": "某公路工程",
        "page_count": 120,
        "created_by": 1,
        "created_at": None,
    }
    summary.update(overrides)
    return summary


def test_upload_template_requires_admin() -> None:
    app.dependency_overrides[auth_service.get_current_user] = _normal_user

    response = client.post(
        "/api/templates",
        data={"name": "公路模板", "project_type": "公路工程"},
        files={"file": ("road.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 403


def test_upload_template_admin_creates(monkeypatch) -> None:
    captured = {}

    def fake_create_template(file_bytes, filename, name, **kwargs):
        captured.update(filename=filename, name=name, **kwargs)
        return _template_summary(name=name)

    monkeypatch.setattr(
        "api.main.template_service.create_template", fake_create_template
    )

    response = client.post(
        "/api/templates",
        data={
            "name": "公路模板",
            "project_type": "公路工程",
            "specialty": "道路",
            "tags": "公路,市政",
        },
        files={"file": ("road.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["template"]["name"] == "公路模板"
    assert captured["project_type"] == "公路工程"
    assert captured["tags"] == ["公路", "市政"]
    assert captured["created_by"] == 1


def test_list_templates_returns_items(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.template_service.list_templates",
        lambda: [_template_summary(), _template_summary(id=2, name="房建模板")],
    )

    response = client.get("/api/templates")

    assert response.status_code == 200
    assert len(response.json()["templates"]) == 2


def test_recommend_templates_passes_criteria(monkeypatch) -> None:
    captured = {}

    def fake_recommend(**kwargs):
        captured.update(kwargs)
        return [
            {
                "template": _template_summary(),
                "match_score": 5.0,
                "match_reasons": ["项目类型匹配：公路工程"],
            }
        ]

    monkeypatch.setattr(
        "api.main.template_service.recommend_templates", fake_recommend
    )

    response = client.get(
        "/api/templates/recommend",
        params={"project_type": "公路工程", "project_name": "某公路工程"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"][0]["match_score"] == 5.0
    assert captured["project_type"] == "公路工程"
    assert captured["project_name"] == "某公路工程"


def test_delete_template_requires_admin() -> None:
    app.dependency_overrides[auth_service.get_current_user] = _normal_user

    response = client.delete("/api/templates/1")

    assert response.status_code == 403


def test_delete_template_admin_ok(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        "api.main.template_service.delete_template",
        lambda template_id: captured.update(template_id=template_id),
    )

    response = client.delete("/api/templates/5")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured == {"template_id": 5}


def test_update_template_admin_renames(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.template_service.update_template",
        lambda template_id, **kwargs: _template_summary(
            id=template_id, name=kwargs.get("name") or "公路模板"
        ),
    )

    response = client.patch("/api/templates/1", json={"name": "公路模板V2"})

    assert response.status_code == 200
    assert response.json()["template"]["name"] == "公路模板V2"


def test_set_project_template(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.template_service.set_project_template",
        lambda project_id, template_id: {
            "project_id": project_id,
            "template_id": template_id,
        },
    )

    response = client.patch("/api/project/7/template", json={"template_id": 3})

    assert response.status_code == 200
    assert response.json() == {"project_id": 7, "template_id": 3}
