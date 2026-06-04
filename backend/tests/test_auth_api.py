from fastapi.testclient import TestClient

from api.main import app
from schemas.auth import LoginResponse, UserProfile
from services import auth_service


client = TestClient(app)


def test_login_returns_access_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.auth_service.authenticate_user",
        lambda username, password: LoginResponse(
            access_token="jwt-token",
            expires_in=3600,
            user=UserProfile(id=1, username=username, display_name="管理员", role="admin"),
        ),
    )

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "tenderdoc"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "jwt-token"
    assert response.json()["user"]["username"] == "admin"


def test_login_rejects_bad_credentials(monkeypatch) -> None:
    def reject(_username, _password):
        raise auth_service.AuthError("账号或密码不正确")

    monkeypatch.setattr("api.main.auth_service.authenticate_user", reject)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "bad"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "账号或密码不正确"


def test_me_requires_bearer_token() -> None:
    app.dependency_overrides.clear()

    response = client.get("/api/auth/me")

    assert response.status_code == 401
