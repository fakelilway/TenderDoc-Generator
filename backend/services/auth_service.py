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
from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor

from core.config import settings
from schemas.auth import (
    LoginResponse,
    RegisterRequest,
    UserAdminProfile,
    UserCreateRequest,
    UserPermissionsUpdateRequest,
    UserProfile,
)
from services.project_service import _connect


HASH_ITERATIONS = 260_000
TOKEN_ALGORITHM = "HS256"
REGISTRATION_CODE_TTL_HOURS = 24
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


def authenticate_user(
    username: str,
    password: str,
    account_type: str | None = None,
) -> LoginResponse:
    ensure_default_admin()
    user = _get_user_by_username(username)
    if not user or not user["is_active"]:
        raise AuthError("账号或密码不正确")
    if not verify_password(password, str(user["password_hash"])):
        raise AuthError("账号或密码不正确")
    if account_type:
        requested_role = account_type.strip().lower()
        if requested_role == "admin" and user["role"] != "admin":
            raise AuthError("账号类型不匹配")
        if requested_role == "user" and user["role"] != "user":
            raise AuthError("账号类型不匹配")

    _mark_last_login(int(user["id"]))
    profile = _profile_from_row(user)
    return _login_response_for_profile(profile)


def register_user(request: RegisterRequest) -> LoginResponse:
    username = request.username.strip()
    if not username:
        raise ValueError("Username is required")
    code_hash = _registration_code_hash(request.verification_code)
    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM registration_codes
                    WHERE code_hash = %s
                      AND used_at IS NULL
                      AND expires_at > NOW()
                    """,
                    (code_hash,),
                )
                code_row = cursor.fetchone()
                if not code_row:
                    raise ValueError("验证码无效或已过期")

                cursor.execute(
                    """
                    INSERT INTO users (
                        username,
                        password_hash,
                        display_name,
                        role,
                        can_view_knowledge,
                        can_edit_knowledge
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        username,
                        display_name,
                        role,
                        is_active,
                        can_view_knowledge,
                        can_edit_knowledge
                    """,
                    (
                        username,
                        hash_password(request.password),
                        request.display_name,
                        "user",
                        False,
                        False,
                    ),
                )
                user = cursor.fetchone()
                cursor.execute(
                    """
                    UPDATE registration_codes
                    SET used_by = %s,
                        used_at = NOW()
                    WHERE id = %s
                    """,
                    (user["id"], code_row["id"]),
                )
    except IntegrityError as error:
        raise ValueError("Username already exists") from error

    profile = _profile_from_row(dict(user))
    return _login_response_for_profile(profile)


def _login_response_for_profile(profile: UserProfile) -> LoginResponse:
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


def require_admin(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin permission required")
    return current_user


def require_knowledge_view(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin permission required")
    return current_user


def require_knowledge_edit(
    current_user: Annotated[UserProfile, Depends(get_current_user)],
) -> UserProfile:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin permission required")
    return current_user


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
                INSERT INTO users (
                    username,
                    password_hash,
                    display_name,
                    role,
                    can_view_knowledge,
                    can_edit_knowledge
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (LOWER(username)) DO NOTHING
                """,
                (
                    username,
                    hash_password(password),
                    settings.default_admin_display_name,
                    "admin",
                    True,
                    True,
                ),
            )


def list_users() -> list[UserAdminProfile]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    username,
                    display_name,
                    role,
                    is_active,
                    can_view_knowledge,
                    can_edit_knowledge
                FROM users
                ORDER BY role = 'admin' DESC, id ASC
                """
            )
            rows = cursor.fetchall()
    return [_admin_profile_from_row(dict(row)) for row in rows]


def create_user(request: UserCreateRequest) -> UserAdminProfile:
    username = request.username.strip()
    if not username:
        raise ValueError("Username is required")
    try:
        with _connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        username,
                        password_hash,
                        display_name,
                        role,
                        can_view_knowledge,
                        can_edit_knowledge
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        username,
                        display_name,
                        role,
                        is_active,
                        can_view_knowledge,
                        can_edit_knowledge
                    """,
                    (
                        username,
                        hash_password(request.password),
                        request.display_name,
                        "user",
                        False,
                        False,
                    ),
                )
                row = cursor.fetchone()
    except IntegrityError as error:
        raise ValueError("Username already exists") from error
    return _admin_profile_from_row(dict(row))


def create_registration_code(admin_user_id: int) -> dict[str, str]:
    code = _new_registration_code()
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=REGISTRATION_CODE_TTL_HOURS
    )
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registration_codes (code_hash, created_by, expires_at)
                VALUES (%s, %s, %s)
                """,
                (_registration_code_hash(code), admin_user_id, expires_at),
            )
    return {"code": code, "expires_at": expires_at.isoformat()}


def update_user_permissions(
    user_id: int,
    request: UserPermissionsUpdateRequest,
) -> UserAdminProfile:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE users
                SET display_name = %s,
                    is_active = CASE WHEN role = 'admin' THEN TRUE ELSE %s END,
                    can_view_knowledge = CASE WHEN role = 'admin' THEN TRUE ELSE %s END,
                    can_edit_knowledge = CASE WHEN role = 'admin' THEN TRUE ELSE %s END
                WHERE id = %s
                RETURNING
                    id,
                    username,
                    display_name,
                    role,
                    is_active,
                    can_view_knowledge,
                    can_edit_knowledge
                """,
                (
                    request.display_name,
                    request.is_active,
                    False,
                    False,
                    user_id,
                ),
            )
            row = cursor.fetchone()
    if not row:
        raise ValueError(f"User {user_id} was not found")
    return _admin_profile_from_row(dict(row))


def delete_user(user_id: int) -> None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT role FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"User {user_id} was not found")
            if row["role"] == "admin":
                raise ValueError("Admin users cannot be deleted")
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))


def _get_user_by_username(username: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    username,
                    password_hash,
                    display_name,
                    role,
                    is_active,
                    can_view_knowledge,
                    can_edit_knowledge
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
                SELECT
                    id,
                    username,
                    password_hash,
                    display_name,
                    role,
                    is_active,
                    can_view_knowledge,
                    can_edit_knowledge
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


def _new_registration_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(2)
    )


def _registration_code_hash(code: str) -> str:
    normalized = code.strip().replace(" ", "").upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _profile_from_row(row: dict[str, Any]) -> UserProfile:
    is_admin = row.get("role") == "admin"
    can_edit_knowledge = is_admin or bool(row.get("can_edit_knowledge"))
    return UserProfile(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=row.get("display_name"),
        role=str(row["role"]),
        can_view_knowledge=is_admin
        or bool(row.get("can_view_knowledge"))
        or can_edit_knowledge,
        can_edit_knowledge=can_edit_knowledge,
    )


def _admin_profile_from_row(row: dict[str, Any]) -> UserAdminProfile:
    profile = _profile_from_row(row)
    return UserAdminProfile(
        **profile.model_dump(),
        is_active=bool(row.get("is_active")),
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
