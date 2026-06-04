from datetime import timedelta

import pytest

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
