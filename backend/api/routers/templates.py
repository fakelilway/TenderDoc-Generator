from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from api.deps import _raise_http_error
from schemas.auth import UserProfile
from schemas.template import (
    TemplateDeleteResponse,
    TemplateListResponse,
    TemplateRecommendation,
    TemplateRecommendResponse,
    TemplateSummary,
    TemplateUpdateRequest,
    TemplateUploadResponse,
)
from services import auth_service, template_service


router = APIRouter()


@router.post("/api/templates", response_model=TemplateUploadResponse)
async def upload_template(
    file: UploadFile = File(...),
    name: str = Form(...),
    project_type: str | None = Form(None),
    specialty: str | None = Form(None),
    envelope_type: str | None = Form(None),
    region: str | None = Form(None),
    project_year: int | None = Form(None),
    tags: str | None = Form(None),
    current_user: UserProfile = Depends(auth_service.require_admin),
) -> TemplateUploadResponse:
    try:
        parsed_tags = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]
        template = template_service.create_template(
            file_bytes=await file.read(),
            filename=file.filename or "template.pdf",
            name=name,
            project_type=project_type,
            specialty=specialty,
            envelope_type=envelope_type,
            region=region,
            project_year=project_year,
            tags=parsed_tags,
            created_by=current_user.id,
        )
    except Exception as error:
        _raise_http_error(error)

    return TemplateUploadResponse(template=TemplateSummary(**template))


@router.get("/api/templates", response_model=TemplateListResponse)
def list_templates(
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> TemplateListResponse:
    try:
        templates = template_service.list_templates()
    except Exception as error:
        _raise_http_error(error)

    return TemplateListResponse(
        templates=[TemplateSummary(**template) for template in templates]
    )


@router.get("/api/templates/recommend", response_model=TemplateRecommendResponse)
def recommend_templates(
    project_type: str | None = Query(None),
    specialty: str | None = Query(None),
    envelope_type: str | None = Query(None),
    region: str | None = Query(None),
    project_year: int | None = Query(None),
    project_name: str | None = Query(None),
    limit: int = Query(3, ge=1, le=20),
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> TemplateRecommendResponse:
    try:
        recommendations = template_service.recommend_templates(
            project_type=project_type,
            specialty=specialty,
            envelope_type=envelope_type,
            region=region,
            project_year=project_year,
            project_name=project_name,
            limit=limit,
        )
    except Exception as error:
        _raise_http_error(error)

    return TemplateRecommendResponse(
        recommendations=[
            TemplateRecommendation(
                template=TemplateSummary(**item["template"]),
                match_score=item["match_score"],
                match_reasons=item["match_reasons"],
            )
            for item in recommendations
        ]
    )


@router.patch("/api/templates/{template_id}", response_model=TemplateUploadResponse)
def update_template(
    template_id: int,
    request: TemplateUpdateRequest,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> TemplateUploadResponse:
    try:
        template = template_service.update_template(
            template_id,
            name=request.name,
            project_type=request.project_type,
            specialty=request.specialty,
            envelope_type=request.envelope_type,
            region=request.region,
            project_year=request.project_year,
            tags=request.tags,
        )
    except Exception as error:
        _raise_http_error(error)

    return TemplateUploadResponse(template=TemplateSummary(**template))


@router.delete("/api/templates/{template_id}", response_model=TemplateDeleteResponse)
def delete_template(
    template_id: int,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> TemplateDeleteResponse:
    try:
        template_service.delete_template(template_id)
    except Exception as error:
        _raise_http_error(error)

    return TemplateDeleteResponse(ok=True)
