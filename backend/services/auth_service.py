from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg2.extras import RealDictCursor

from core.config import settings
from schemas.auth import LoginResponse, UserProfile
from services.project_service import _connect


HASH_ITERATIONS = 260_000
TOKEN_ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)


class AuthError(ValueError):
    pass


def hash_password(password: str, salt: str | None = None) -> str:
    if not password:
        raise ValueError("Password is required")
    salt = salt or secrets.token_urlsafe(24)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS,
    )
    encoded = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    )
    actual = base64.urlsafe_b64encode(digest).decode("ascii")
    return hmac.compare_digest(actual, expected)


def authenticate_user(username: str, password: str) -> LoginResponse:
    ensure_default_admin()
    user = _get_user_by_username(username)
    if not user or not user["is_active"]:
        raise AuthError("账号或密码不正确")
    if not verify_password(password, str(user["password_hash"])):
        raise AuthError("账号或密码不正确")

    _mark_last_login(int(user["id"]))
    profile = _profile_from_row(user)
    expires_delta = timedelta(minutes=settings.jwt_expires_minutes)
    token = create_access_token(
        {
            "sub": str(profile.id),
            "username": profile.username,
            "role": profile.role,
        },
        expires_delta=expires_delta,
    )
    return LoginResponse(
        access_token=token,
        expires_in=int(expires_delta.total_seconds()),
        user=profile,
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> UserProfile:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise_auth_required()

    try:
        payload = decode_access_token(credentials.credentials)
    except AuthError:
        raise_auth_required()

    user_id = payload.get("sub")
    if not user_id:
        raise_auth_required()

    user = _get_user_by_id(int(user_id))
    if not user or not user["is_active"]:
        raise_auth_required()
    return _profile_from_row(user)


def raise_auth_required() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(
    payload: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + (expires_delta or timedelta(minutes=settings.jwt_expires_minutes))
    token_payload = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    signing_input = (
        _base64url_json(header) + "." + _base64url_json(token_payload)
    )
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return signing_input + "." + _base64url_encode(signature)


def decode_access_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Invalid token")
    signing_input = ".".join(parts[:2])
    expected_signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_base64url_encode(expected_signature), parts[2]):
        raise AuthError("Invalid token")

    payload = json.loads(_base64url_decode(parts[1]).decode("utf-8"))
    expires_at = int(payload.get("exp", 0))
    if expires_at <= int(datetime.now(timezone.utc).timestamp()):
        raise AuthError("Token expired")
    return payload


def ensure_default_admin() -> None:
    username = settings.default_admin_username.strip()
    password = settings.default_admin_password
    if not username or not password:
        return
    if _get_user_by_username(username):
        return

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, display_name, role)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (LOWER(username)) DO NOTHING
                """,
                (
                    username,
                    hash_password(password),
                    settings.default_admin_display_name,
                    "admin",
                ),
            )


def _get_user_by_username(username: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, username, password_hash, display_name, role, is_active
                FROM users
                WHERE LOWER(username) = LOWER(%s)
                """,
                (username.strip(),),
            )
            row = cursor.fetchone()
    return dict(row) if row else None


def _get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, username, password_hash, display_name, role, is_active
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
    return dict(row) if row else None


def _mark_last_login(user_id: int) -> None:
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET last_login_at = NOW() WHERE id = %s",
                (user_id,),
            )


def _profile_from_row(row: dict[str, Any]) -> UserProfile:
    return UserProfile(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=row.get("display_name"),
        role=str(row["role"]),
    )


def _base64url_json(payload: dict[str, Any]) -> str:
    return _base64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
