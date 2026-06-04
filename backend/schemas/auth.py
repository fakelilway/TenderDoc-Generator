from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserProfile(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile


class AuthMeResponse(BaseModel):
    user: UserProfile


class LogoutResponse(BaseModel):
    ok: bool = True
