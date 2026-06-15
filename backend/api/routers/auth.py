from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import _raise_http_error
from schemas.auth import (
    AuthMeResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RegisterRequest,
    UserProfile,
)
from services import auth_service


router = APIRouter()


@router.post("/api/auth/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    try:
        return auth_service.authenticate_user(
            request.username,
            request.password,
            account_type=request.account_type,
        )
    except auth_service.AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except Exception as error:
        _raise_http_error(error)


@router.post("/api/auth/register", response_model=LoginResponse)
def register(request: RegisterRequest) -> LoginResponse:
    try:
        return auth_service.register_user(request)
    except Exception as error:
        _raise_http_error(error)


@router.get("/api/auth/me", response_model=AuthMeResponse)
def auth_me(
    current_user: UserProfile = Depends(auth_service.get_current_user),
) -> AuthMeResponse:
    return AuthMeResponse(user=current_user)


@router.post("/api/auth/logout", response_model=LogoutResponse)
def logout(
    current_user: UserProfile = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    del current_user
    return LogoutResponse(ok=True)
