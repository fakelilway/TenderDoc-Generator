import logging
from datetime import timedelta

import pytest

from core.config import DEFAULT_JWT_SECRET, settings, validate_security_settings
from schemas.auth import UserPermissionsUpdateRequest
from services import auth_service


def test_password_hash_round_trip() -> None:
    password_hash = auth_service.hash_password("tenderdoc")

    assert password_hash != "tenderdoc"
    assert auth_service.verify_password("tenderdoc", password_hash)
    assert not auth_service.verify_password("wrong", password_hash)


def test_access_token_round_trip() -> None:
    token = auth_service.create_access_token(
        {"sub": "7", "username": "admin", "role": "admin"},
        expires_delta=timedelta(minutes=5),
    )

    payload = auth_service.decode_access_token(token)

    assert payload["sub"] == "7"
    assert payload["username"] == "admin"
    assert payload["role"] == "admin"


def test_expired_access_token_is_rejected() -> None:
    token = auth_service.create_access_token(
        {"sub": "7"},
        expires_delta=timedelta(seconds=-1),
    )

    with pytest.raises(auth_service.AuthError):
        auth_service.decode_access_token(token)


def test_default_jwt_secret_is_rejected_when_debug_is_off() -> None:
    insecure = settings.model_copy(
        update={"jwt_secret": DEFAULT_JWT_SECRET, "debug": False}
    )

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_security_settings(insecure)


def test_default_jwt_secret_logs_warning_in_debug(caplog) -> None:
    insecure = settings.model_copy(
        update={"jwt_secret": DEFAULT_JWT_SECRET, "debug": True}
    )

    with caplog.at_level(logging.WARNING, logger="core.config"):
        validate_security_settings(insecure)

    assert any("JWT_SECRET" in record.message for record in caplog.records)


def test_custom_jwt_secret_passes_validation() -> None:
    secure = settings.model_copy(
        update={"jwt_secret": "a-long-random-secret", "debug": False}
    )

    validate_security_settings(secure)


def test_authenticate_rejects_wrong_account_type(monkeypatch) -> None:
    monkeypatch.setattr(auth_service, "ensure_default_admin", lambda: None)
    monkeypatch.setattr(
        auth_service,
        "_get_user_by_username",
        lambda username: {
            "id": 2,
            "username": username,
            "password_hash": auth_service.hash_password("secret1"),
            "display_name": "演示用户",
            "role": "user",
            "is_active": True,
            "can_view_knowledge": False,
            "can_edit_knowledge": False,
        },
    )

    with pytest.raises(auth_service.AuthError, match="账号类型不匹配"):
        auth_service.authenticate_user("demo", "secret1", account_type="admin")


def test_admin_permissions_are_effective_even_if_row_flags_are_false() -> None:
    profile = auth_service._profile_from_row(
        {
            "id": 1,
            "username": "admin",
            "display_name": "管理员",
            "role": "admin",
            "can_view_knowledge": False,
            "can_edit_knowledge": False,
        }
    )

    assert profile.can_view_knowledge is True
    assert profile.can_edit_knowledge is True


def test_user_permissions_cannot_grant_knowledge_access(monkeypatch) -> None:
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def execute(self, _sql, params):
            captured["params"] = params

        def fetchone(self):
                return {
                    "id": 2,
                    "username": "demo",
                    "display_name": "演示用户",
                    "role": "user",
                    "is_active": True,
                    "can_view_knowledge": False,
                    "can_edit_knowledge": False,
                }

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def cursor(self, cursor_factory=None):
            return FakeCursor()

    monkeypatch.setattr(auth_service, "_connect", lambda: FakeConnection())

    profile = auth_service.update_user_permissions(
        2,
        UserPermissionsUpdateRequest(
            display_name="演示用户",
            is_active=True,
            can_view_knowledge=False,
            can_edit_knowledge=True,
        ),
    )

    assert captured["params"][2] is False
    assert captured["params"][3] is False
    assert profile.can_view_knowledge is False
    assert profile.can_edit_knowledge is False
