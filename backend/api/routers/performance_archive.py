from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import _raise_http_error
from schemas.auth import UserProfile
from services import auth_service, performance_archive_service

router = APIRouter()


class ReassignRequest(BaseModel):
    document_ids: list[int]
    target_project: str


class RenameRequest(BaseModel):
    title: str


@router.get("/api/performance-archive")
def get_performance_archive(
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> dict:
    """业绩档案:台账↔证明对号 + 各项目证据包 + 台账清单(供认领下拉)。"""
    try:
        archive = performance_archive_service.build_archive()
        archive["ledger_all"] = performance_archive_service.list_performance_ledger()
        return archive
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)


@router.post("/api/performance-archive/reassign")
def reassign_evidence(
    request: ReassignRequest,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> dict:
    """改归属/认领/合并:把证明改挂到目标项目名下。"""
    try:
        changed = performance_archive_service.reassign_evidence(
            request.document_ids, request.target_project
        )
        return {"ok": True, "changed": changed}
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)


@router.patch("/api/performance-archive/evidence/{document_id}")
def rename_evidence(
    document_id: int,
    request: RenameRequest,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> dict:
    """给单张业绩证明改名。"""
    try:
        performance_archive_service.rename_evidence(document_id, request.title)
        return {"ok": True}
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)
