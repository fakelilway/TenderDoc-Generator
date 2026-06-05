from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    account_type: str | None = None


class UserProfile(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str
    can_view_knowledge: bool = False
    can_edit_knowledge: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile


class AuthMeResponse(BaseModel):
    user: UserProfile


class LogoutResponse(BaseModel):
    ok: bool = True


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=6)
    display_name: str | None = None
    verification_code: str = Field(..., min_length=1)


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=6)
    display_name: str | None = None
    can_view_knowledge: bool = False
    can_edit_knowledge: bool = False


class UserPermissionsUpdateRequest(BaseModel):
    display_name: str | None = None
    is_active: bool = True
    can_view_knowledge: bool = False
    can_edit_knowledge: bool = False


class UserAdminProfile(UserProfile):
    is_active: bool


class UserListResponse(BaseModel):
    users: list[UserAdminProfile]


class UserResponse(BaseModel):
    user: UserAdminProfile


class RegistrationCodeResponse(BaseModel):
    code: str
    expires_at: str


class UserDeleteResponse(BaseModel):
    ok: bool = True
