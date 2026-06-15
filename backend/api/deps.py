from __future__ import annotations

import logging
import uuid

from fastapi import Depends, HTTPException

from core.config import settings
from schemas.auth import UserProfile
from services import auth_service, project_service
from services.project_service import ProjectAccessError, ProjectNotFoundError
from services.template_service import TemplateNotFoundError


logger = logging.getLogger(__name__)


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, HTTPException):
        raise error
    if isinstance(error, (ProjectNotFoundError, TemplateNotFoundError)):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, ProjectAccessError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400, detail=str(error)) from error

    request_id = uuid.uuid4().hex
    logger.exception("Unhandled API error (request_id=%s)", request_id)
    if settings.debug:
        raise HTTPException(status_code=500, detail=str(error)) from error
    raise HTTPException(
        status_code=500,
        detail=f"服务器内部错误，请稍后重试（请求编号：{request_id}）",
    ) from error


def authorized_project(
    project_id: int,
    current_user: UserProfile = Depends(auth_service.get_current_user),
) -> int:
    """Dependency that enforces project ownership for project-scoped routes."""
    try:
        project_service.authorize_project_access(
            project_id,
            current_user.id,
            is_admin=current_user.role == "admin",
        )
    except Exception as error:
        _raise_http_error(error)
    return project_id
