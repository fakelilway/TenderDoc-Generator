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
from schemas.knowledge import (
    KnowledgeDeleteResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentSummary,
    KnowledgeUploadResponse,
)
from schemas.personnel import (
    PMRecommendationResponse,
    PMSelectionRequest,
    PMSelectionResponse,
)
from schemas.tender_spec import ConformanceReportResponse
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
from services import (
    auth_service,
    knowledge_service,
    project_service,
    template_service,
    workflow_service,
)


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


@router.post(
    "/api/project/{project_id}/material",
    response_model=KnowledgeUploadResponse,
)
async def upload_project_material(
    project_id: int,
    file: UploadFile = File(...),
    document_category: str | None = Form(None),
    specialty: str | None = Form(None),
    tags: str | None = Form(None),
    target_section: str | None = Form(None),
    caption: str | None = Form(None),
    _project: int = Depends(authorized_project),
) -> KnowledgeUploadResponse:
    """本项目专用材料:两种角色按文件类型自动分流。

    - 图片(航拍图/本项目图纸…)→ ② 插入素材:标 image_insertable + target_section,生成时
      按节插到技术卷对应节(见 v2_generation._inject_project_images)。
    - 其它(文本)→ M23 接地素材:project_id 隔离入库、rag_text 索引,grounding 技术卷生成。
    """
    try:
        parsed_tags = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]
        filename = file.filename or "material.txt"
        file_bytes = await file.read()
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        is_image = suffix in {"jpg", "jpeg", "png", "gif", "bmp", "webp"} or (
            file.content_type or ""
        ).startswith("image/")
        if is_image:
            indexed = knowledge_service.index_uploaded_knowledge(
                file_bytes=file_bytes,
                filename=filename,
                content_type=file.content_type,
                document_category="图片资料",
                document_type="本项目图纸",
                image_insertable=True,
                tags=parsed_tags or None,
                project_id=project_id,
                extra_metadata={
                    "target_section": (target_section or "").strip(),
                    "caption": (caption or "").strip(),
                },
            )
            return KnowledgeUploadResponse(**indexed)
        indexed = knowledge_service.index_uploaded_knowledge(
            file_bytes=file_bytes,
            filename=filename,
            content_type=file.content_type,
            document_category=document_category or "施工方案",
            document_type="施工方案",
            volume="技术文件",
            specialty=specialty,
            tags=parsed_tags or None,
            ingestion_mode="rag_text",
            project_id=project_id,
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeUploadResponse(**indexed)


@router.get(
    "/api/project/{project_id}/material",
    response_model=KnowledgeDocumentListResponse,
)
def list_project_material(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> KnowledgeDocumentListResponse:
    try:
        documents = knowledge_service.list_project_materials(project_id)
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDocumentListResponse(
        documents=[KnowledgeDocumentSummary(**doc) for doc in documents]
    )


@router.delete(
    "/api/project/{project_id}/material/{document_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_project_material(
    project_id: int,
    document_id: int,
    _project: int = Depends(authorized_project),
) -> KnowledgeDeleteResponse:
    try:
        knowledge_service.delete_project_material(project_id, document_id)
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDeleteResponse(ok=True)


@router.get(
    "/api/project/{project_id}/personnel/recommendations",
    response_model=PMRecommendationResponse,
)
def get_project_personnel_recommendations(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> PMRecommendationResponse:
    """派生招标项目经理要求 + 从公司名册推荐匹配候选(按等级+专业排序)。"""
    try:
        result = project_service.recommend_project_personnel(project_id)
    except Exception as error:
        _raise_http_error(error)

    return PMRecommendationResponse(**result)


@router.put(
    "/api/project/{project_id}/personnel",
    response_model=PMSelectionResponse,
)
def save_project_personnel_selection(
    project_id: int,
    request: PMSelectionRequest,
    _project: int = Depends(authorized_project),
) -> PMSelectionResponse:
    """选定/清空本项目项目经理。member=None 清空。"""
    try:
        member = (
            request.project_manager.model_dump()
            if request.project_manager is not None
            else None
        )
        result = project_service.save_selected_project_manager(project_id, member)
    except Exception as error:
        _raise_http_error(error)

    return PMSelectionResponse(**result)


@router.get(
    "/api/project/{project_id}/conformance",
    response_model=ConformanceReportResponse,
)
def get_project_conformance(
    project_id: int,
    _project: int = Depends(authorized_project),
) -> ConformanceReportResponse:
    """逐空核对报告:读懂招标→每个空"找要求→核对我方→符合填/不符合告警"。"""
    from services import tender_spec_service

    try:
        report = tender_spec_service.build_project_conformance_report(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ConformanceReportResponse(
        project_id=report.project_id,
        items=report.items,
        has_blocking=report.has_blocking,
        warning_count=len(report.warnings),
        pending_count=len(report.pending_manual),
    )


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

