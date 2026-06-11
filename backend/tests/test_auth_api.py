import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.config import DEFAULT_JWT_SECRET, settings
from schemas.auth import LoginResponse, UserProfile
from services import auth_service


client = TestClient(app)


def test_startup_rejects_default_jwt_secret_when_not_debug(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", DEFAULT_JWT_SECRET)
    monkeypatch.setattr(settings, "debug", False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(app):
            pass


def test_login_returns_access_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.auth_service.authenticate_user",
        lambda username, password, account_type=None: LoginResponse(
            access_token="jwt-token",
            expires_in=3600,
            user=UserProfile(id=1, username=username, display_name="管理员", role="admin"),
        ),
    )

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "tenderdoc", "account_type": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "jwt-token"
    assert response.json()["user"]["username"] == "admin"


def test_login_rejects_bad_credentials(monkeypatch) -> None:
    def reject(_username, _password, account_type=None):
        raise auth_service.AuthError("账号或密码不正确")

    monkeypatch.setattr("api.main.auth_service.authenticate_user", reject)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "bad"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "账号或密码不正确"


def test_register_returns_login_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.auth_service.register_user",
        lambda request: LoginResponse(
            access_token="registered-token",
            expires_in=3600,
            user=UserProfile(
                id=2,
                username=request.username,
                display_name=request.display_name,
                role="user",
            ),
        ),
    )

    response = client.post(
        "/api/auth/register",
        json={
            "username": "demo",
            "password": "secret1",
            "display_name": "演示用户",
            "verification_code": "ABCD-2345",
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "registered-token"
    assert response.json()["user"]["role"] == "user"


def test_me_requires_bearer_token() -> None:
    app.dependency_overrides.clear()

    response = client.get("/api/auth/me")

    assert response.status_code == 401
