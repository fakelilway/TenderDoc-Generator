from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import _raise_http_error
from schemas.auth import UserProfile
from schemas.company import CompanyProfile, CompanyProfileResponse
from services import auth_service, company_profile_service


router = APIRouter()


@router.get("/api/company-profile", response_model=CompanyProfileResponse)
def read_company_profile(
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> CompanyProfileResponse:
    try:
        result = company_profile_service.get_company_profile()
    except Exception as error:
        _raise_http_error(error)
    return CompanyProfileResponse(
        profile=CompanyProfile(**result["profile"]),
        updated_at=result["updated_at"],
    )


@router.put("/api/company-profile", response_model=CompanyProfileResponse)
def update_company_profile(
    request: CompanyProfile,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> CompanyProfileResponse:
    try:
        result = company_profile_service.save_company_profile(request.model_dump())
    except Exception as error:
        _raise_http_error(error)
    return CompanyProfileResponse(
        profile=CompanyProfile(**result["profile"]),
        updated_at=result["updated_at"],
    )
