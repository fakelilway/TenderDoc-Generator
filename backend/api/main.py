from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import settings, validate_security_settings
from core.db import close_pool

# Re-exported for backward compatibility (tests monkeypatch ``api.main.<module>``
# attributes and import these names directly from ``api.main``).
from api.deps import _raise_http_error, authorized_project
from api.routers import (
    admin as admin_router,
    auth as auth_router,
    cert_archive as cert_archive_router,
    company as company_router,
    knowledge as knowledge_router,
    performance_archive as performance_archive_router,
    project as project_router,
)
from rag import retriever
from services import (
    auth_service,
    company_profile_service,
    knowledge_service,
    project_service,
    workflow_service,
)
from services.project_service import ProjectAccessError, ProjectNotFoundError


logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    validate_security_settings(settings)
    yield
    close_pool()


app = FastAPI(title="TenderDoc Generator API", lifespan=_lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(company_router.router)
app.include_router(knowledge_router.router)
app.include_router(performance_archive_router.router)
app.include_router(cert_archive_router.router)
app.include_router(project_router.router)


__all__ = [
    "app",
    "authorized_project",
    "_raise_http_error",
    "auth_service",
    "company_profile_service",
    "knowledge_service",
    "project_service",
    "workflow_service",
    "retriever",
    "ProjectAccessError",
    "ProjectNotFoundError",
]
