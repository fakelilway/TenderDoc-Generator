from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
)

from api.deps import _raise_http_error, authorized_project
from schemas.auth import UserProfile
from schemas.project import (
    ProjectCreateResponse,
    ProjectDeleteResponse,
    ProjectDeliveryPreviewResponse,
    ProjectDownloadResponse,
    ProjectListResponse,
    ProjectResultResponse,
    ProjectStatusResponse,
    ProjectSummary,
    ProjectTemplateRequest,
    ProjectTemplateResponse,
)
from schemas.strategy import (
    ProjectPricingStrategyResponse,
    ProjectResponseMatrixResponse,
    ProjectScorePredictionResponse,
)
from schemas.workflow import (
    BidOutlineRequest,
    BidOutlineResponse,
    DraftMarkdownRequest,
    DraftMarkdownResponse,
    FinalChecklistResponse,
    KnowledgeSelectionRequest,
    KnowledgeSelectionResponse,
    ParsedConfirmationRequest,
    ParsedConfirmationResponse,
    ProjectConfirmRequest,
    ProjectConfirmResponse,
    WorkflowRunResponse,
)
from services import auth_service, project_service, template_service, workflow_service


router = APIRouter()


@router.post("/api/project/create", response_model=ProjectCreateResponse)
async def create_project(
    name: str = Form(...),
    tender_file: UploadFile = File(...),
    template_id: int | None = Form(None),
    current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectCreateResponse:
    try:
        project = project_service.create_project(
            name=name,
            file_bytes=await tender_file.read(),
            filename=tender_file.filename or "tender.txt",
            content_type=tender_file.content_type,
            owner_user_id=current_user.id,
            template_id=template_id,
        )
    except Exception as error:
        _raise_http_error(error)

    return ProjectCreateResponse(
        project_id=project["id"],
        status=project["status"],
        tender_file_path=project["tender_file_path"],
    )


@router.get("/api/projects", response_model=ProjectListResponse)
def list_projects(
    owner_user_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectListResponse:
    is_admin = current_user.role == "admin"
    try:
        projects = project_service.list_projects(
            viewer_id=current_user.id,
            is_admin=is_admin,
            owner_user_id=owner_user_id if is_admin else None,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        _raise_http_error(error)

    return ProjectListResponse(
        projects=[ProjectSummary(**project) for project in projects]
    )


@router.get("/api/project/{project_id}/status", response_model=ProjectStatusResponse)
def project_status(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ProjectStatusResponse:
    try:
        return ProjectStatusResponse(**project_service.get_project_status(project_id))
    except Exception as error:
        _raise_http_error(error)


@router.post("/api/project/{project_id}/parse", response_model=ProjectResultResponse)
def parse_project(
    project_id: int,
    background_tasks: BackgroundTasks,
    _project: int = Depends(authorized_project),
) -> ProjectResultResponse:
    try:
        project = project_service.start_parse_project(project_id)
        if not project.get("parsed_json"):
            background_tasks.add_task(project_service.parse_project, project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectResultResponse(
        project_id=project["id"],
        status=project["status"],
        parsed_json=project["parsed_json"],
    )


@router.patch(
    "/api/project/{project_id}/parsed",
    response_model=ParsedConfirmationResponse,
)
def confirm_parsed_project(
    project_id: int,
    request: ParsedConfirmationRequest,
    _project: int = Depends(authorized_project),
) -> ParsedConfirmationResponse:
    try:
        project = project_service.confirm_parsed_result(project_id, request.parsed_json)
    except Exception as error:
        _raise_http_error(error)

    return ParsedConfirmationResponse(
        project_id=project["id"],
        status=project["status"],
        confirmed_parsed_json=project["confirmed_parsed_json"],
    )


@router.post("/api/project/{project_id}/outline", response_model=BidOutlineResponse)
def build_project_outline(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> BidOutlineResponse:
    try:
        project = project_service.build_project_outline(project_id)
    except Exception as error:
        _raise_http_error(error)

    return BidOutlineResponse(
        project_id=project["id"],
        status=project["status"],
        bid_outline=project["bid_outline_json"],
        document_outline=project.get("document_outline_json") or [],
    )


@router.patch("/api/project/{project_id}/outline", response_model=BidOutlineResponse)
def save_project_outline(
    project_id: int,
    request: BidOutlineRequest,
    _project: int = Depends(authorized_project),
) -> BidOutlineResponse:
    try:
        project = project_service.save_project_outline(
            project_id,
            request.outline,
            document_outline=request.document_outline,
        )
    except Exception as error:
        _raise_http_error(error)

    return BidOutlineResponse(
        project_id=project["id"],
        status=project["status"],
        bid_outline=project["bid_outline_json"],
        document_outline=project.get("document_outline_json") or [],
    )


@router.patch(
    "/api/project/{project_id}/knowledge-selection",
    response_model=KnowledgeSelectionResponse,
)
def save_project_knowledge_selection(
    project_id: int,
    request: KnowledgeSelectionRequest,
    _project: int = Depends(authorized_project),
) -> KnowledgeSelectionResponse:
    try:
        result = project_service.save_selected_knowledge_chunks(
            project_id,
            request.selected_chunk_ids,
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeSelectionResponse(**result)


@router.patch("/api/project/{project_id}/draft", response_model=DraftMarkdownResponse)
def save_project_draft(
    project_id: int,
    request: DraftMarkdownRequest,
    _project: int = Depends(authorized_project),
) -> DraftMarkdownResponse:
    try:
        result = project_service.save_draft_markdown(project_id, request.markdown)
    except Exception as error:
        _raise_http_error(error)

    return DraftMarkdownResponse(
        project_id=result["id"],
        status=result["status"],
        draft_markdown=result["edited_markdown"],
        review_report=result["review_report_json"],
    )


@router.get(
    "/api/project/{project_id}/final-checklist",
    response_model=FinalChecklistResponse,
)
def get_project_final_checklist(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> FinalChecklistResponse:
    try:
        result = project_service.build_final_checklist(project_id)
    except Exception as error:
        _raise_http_error(error)

    return FinalChecklistResponse(**result)


@router.post(
    "/api/project/{project_id}/pricing-strategy",
    response_model=ProjectPricingStrategyResponse,
)
def build_project_pricing_strategy(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ProjectPricingStrategyResponse:
    try:
        result = project_service.build_project_pricing_strategy(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectPricingStrategyResponse(**result)


@router.post(
    "/api/project/{project_id}/score-prediction",
    response_model=ProjectScorePredictionResponse,
)
def build_project_score_prediction(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ProjectScorePredictionResponse:
    try:
        result = project_service.build_project_score_prediction(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectScorePredictionResponse(**result)


@router.post(
    "/api/project/{project_id}/response-matrix",
    response_model=ProjectResponseMatrixResponse,
)
def build_project_response_matrix(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ProjectResponseMatrixResponse:
    try:
        result = project_service.build_project_response_matrix(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectResponseMatrixResponse(**result)


@router.get("/api/project/{project_id}/download", response_model=ProjectDownloadResponse)
def download_project(
    project_id: int,
    artifact: str = Query("docx"),
    expiry: int = Query(3600, ge=60, le=86400),
    _project: int = Depends(authorized_project),
) -> ProjectDownloadResponse:
    try:
        download_info = project_service.get_project_download_url(
            project_id,
            artifact=artifact,
            expiry=expiry,
        )
    except Exception as error:
        _raise_http_error(error)

    return ProjectDownloadResponse(**download_info)


@router.get(
    "/api/project/{project_id}/delivery-preview",
    response_model=ProjectDeliveryPreviewResponse,
)
def project_delivery_preview(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ProjectDeliveryPreviewResponse:
    try:
        return ProjectDeliveryPreviewResponse(
            **project_service.get_project_delivery_preview(project_id)
        )
    except Exception as error:
        _raise_http_error(error)


@router.post("/api/project/{project_id}/workflow/run", response_model=WorkflowRunResponse)
def run_project_workflow(
    project_id: int,
    background_tasks: BackgroundTasks,
    _project: int = Depends(authorized_project),
) -> WorkflowRunResponse:
    try:
        task = workflow_service.start_bid_workflow(project_id, background_tasks)
    except Exception as error:
        _raise_http_error(error)

    return WorkflowRunResponse(
        project_id=project_id,
        status=str(task["status"]),
        awaiting_human=bool(task["awaiting_human"]),
        iteration_count=int(task["iteration_count"]),
        review_report=task["review_report"],
    )


@router.post("/api/project/{project_id}/confirm", response_model=ProjectConfirmResponse)
def confirm_project(
    project_id: int,
    request: ProjectConfirmRequest,
    _project: int = Depends(authorized_project),
) -> ProjectConfirmResponse:
    try:
        state = workflow_service.confirm_project(
            project_id,
            approved=request.approved,
            corrections=request.corrections,
        )
    except Exception as error:
        _raise_http_error(error)

    return ProjectConfirmResponse(
        project_id=state.project_id,
        status=state.status,
        approved=state.approved,
        review_report=state.review_report,
    )


@router.get("/api/project/{project_id}/result", response_model=ProjectResultResponse)
def project_result(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ProjectResultResponse:
    try:
        return ProjectResultResponse(**project_service.get_project_result(project_id))
    except Exception as error:
        _raise_http_error(error)


@router.get("/api/project/{project_id}/review-report")
def project_review_report(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> dict:
    try:
        return project_service.get_project_review_report(project_id)
    except Exception as error:
        _raise_http_error(error)


@router.delete("/api/project/{project_id}", response_model=ProjectDeleteResponse)
def delete_project(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ProjectDeleteResponse:
    try:
        project_service.delete_project(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectDeleteResponse(ok=True)


@router.patch("/api/project/{project_id}/template", response_model=ProjectTemplateResponse)
def set_project_template(
    project_id: int,
    request: ProjectTemplateRequest,
    _project: int = Depends(authorized_project),
) -> ProjectTemplateResponse:
    try:
        result = template_service.set_project_template(project_id, request.template_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectTemplateResponse(**result)
