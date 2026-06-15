from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import _raise_http_error
from schemas.auth import (
    RegistrationCodeResponse,
    UserCreateRequest,
    UserDeleteResponse,
    UserListResponse,
    UserPermissionsUpdateRequest,
    UserProfile,
    UserResponse,
)
from services import auth_service


router = APIRouter()


@router.get("/api/admin/users", response_model=UserListResponse)
def list_users(
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserListResponse:
    return UserListResponse(users=auth_service.list_users())


@router.post("/api/admin/users", response_model=UserResponse)
def create_user(
    request: UserCreateRequest,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserResponse:
    try:
        user = auth_service.create_user(request)
    except Exception as error:
        _raise_http_error(error)
    return UserResponse(user=user)


@router.post("/api/admin/registration-codes", response_model=RegistrationCodeResponse)
def create_registration_code(
    current_user: UserProfile = Depends(auth_service.require_admin),
) -> RegistrationCodeResponse:
    try:
        code = auth_service.create_registration_code(current_user.id)
    except Exception as error:
        _raise_http_error(error)
    return RegistrationCodeResponse(**code)


@router.patch("/api/admin/users/{user_id}/permissions", response_model=UserResponse)
def update_user_permissions(
    user_id: int,
    request: UserPermissionsUpdateRequest,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserResponse:
    try:
        user = auth_service.update_user_permissions(user_id, request)
    except Exception as error:
        _raise_http_error(error)
    return UserResponse(user=user)


@router.delete("/api/admin/users/{user_id}", response_model=UserDeleteResponse)
def delete_user(
    user_id: int,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserDeleteResponse:
    try:
        auth_service.delete_user(user_id)
    except Exception as error:
        _raise_http_error(error)
    return UserDeleteResponse(ok=True)
