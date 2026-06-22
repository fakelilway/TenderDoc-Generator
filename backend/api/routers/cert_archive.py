from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import _raise_http_error
from schemas.auth import UserProfile
from services import auth_service, cert_archive_service

router = APIRouter()


class PersonReassignRequest(BaseModel):
    document_ids: list[int]
    target_person: str


class CompanyRetypeRequest(BaseModel):
    document_ids: list[int]
    target_type: str


class RenameRequest(BaseModel):
    title: str


@router.get("/api/cert-archive/person")
def get_person_archive(
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> dict:
    try:
        return cert_archive_service.list_person_archive()
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)


@router.get("/api/cert-archive/company")
def get_company_archive(
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> dict:
    try:
        return cert_archive_service.list_company_archive()
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)


@router.post("/api/cert-archive/person/reassign")
def reassign_person(
    request: PersonReassignRequest,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> dict:
    try:
        changed = cert_archive_service.reassign_person_cert(
            request.document_ids, request.target_person
        )
        return {"ok": True, "changed": changed}
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)


@router.post("/api/cert-archive/company/retype")
def retype_company(
    request: CompanyRetypeRequest,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> dict:
    try:
        changed = cert_archive_service.retype_company_cert(
            request.document_ids, request.target_type
        )
        return {"ok": True, "changed": changed}
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)


@router.patch("/api/cert-archive/cert/{document_id}")
def rename_cert(
    document_id: int,
    request: RenameRequest,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> dict:
    try:
        cert_archive_service.rename_cert(document_id, request.title)
        return {"ok": True}
    except Exception as error:  # noqa: BLE001
        _raise_http_error(error)
