from __future__ import annotations

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)

from rag import retriever
from schemas.auth import (
    AuthMeResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RegisterRequest,
    RegistrationCodeResponse,
    UserCreateRequest,
    UserDeleteResponse,
    UserListResponse,
    UserPermissionsUpdateRequest,
    UserProfile,
    UserResponse,
)
from schemas.knowledge import (
    KnowledgeDeleteResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentSummary,
    KnowledgeDocumentUpdateRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeUploadResponse,
)
from schemas.project import (
    ProjectCreateResponse,
    ProjectDownloadResponse,
    ProjectGenerateResponse,
    ProjectResultResponse,
    ProjectReviewResponse,
    ProjectStatusResponse,
)
from schemas.workflow import (
    ProjectConfirmRequest,
    ProjectConfirmResponse,
    WorkflowRunResponse,
)
from services import (
    auth_service,
    generation_service,
    knowledge_service,
    project_service,
    workflow_service,
)
from services.project_service import ProjectNotFoundError


app = FastAPI(title="TenderDoc Generator API")


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, ProjectNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    try:
        return auth_service.authenticate_user(
            request.username,
            request.password,
            account_type=request.account_type,
        )
    except auth_service.AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except Exception as error:
        _raise_http_error(error)


@app.post("/api/auth/register", response_model=LoginResponse)
def register(request: RegisterRequest) -> LoginResponse:
    try:
        return auth_service.register_user(request)
    except Exception as error:
        _raise_http_error(error)


@app.get("/api/auth/me", response_model=AuthMeResponse)
def auth_me(
    current_user: UserProfile = Depends(auth_service.get_current_user),
) -> AuthMeResponse:
    return AuthMeResponse(user=current_user)


@app.post("/api/auth/logout", response_model=LogoutResponse)
def logout(
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    return LogoutResponse(ok=True)


@app.get("/api/admin/users", response_model=UserListResponse)
def list_users(
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserListResponse:
    return UserListResponse(users=auth_service.list_users())


@app.post("/api/admin/users", response_model=UserResponse)
def create_user(
    request: UserCreateRequest,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserResponse:
    try:
        user = auth_service.create_user(request)
    except Exception as error:
        _raise_http_error(error)
    return UserResponse(user=user)


@app.post("/api/admin/registration-codes", response_model=RegistrationCodeResponse)
def create_registration_code(
    current_user: UserProfile = Depends(auth_service.require_admin),
) -> RegistrationCodeResponse:
    try:
        code = auth_service.create_registration_code(current_user.id)
    except Exception as error:
        _raise_http_error(error)
    return RegistrationCodeResponse(**code)


@app.patch("/api/admin/users/{user_id}/permissions", response_model=UserResponse)
def update_user_permissions(
    user_id: int,
    request: UserPermissionsUpdateRequest,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserResponse:
    try:
        user = auth_service.update_user_permissions(user_id, request)
    except Exception as error:
        _raise_http_error(error)
    return UserResponse(user=user)


@app.delete("/api/admin/users/{user_id}", response_model=UserDeleteResponse)
def delete_user(
    user_id: int,
    _current_user: UserProfile = Depends(auth_service.require_admin),
) -> UserDeleteResponse:
    try:
        auth_service.delete_user(user_id)
    except Exception as error:
        _raise_http_error(error)
    return UserDeleteResponse(ok=True)


@app.post("/api/knowledge/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge(
    file: UploadFile = File(...),
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> KnowledgeUploadResponse:
    try:
        indexed = knowledge_service.index_uploaded_knowledge(
            file_bytes=await file.read(),
            filename=file.filename or "knowledge.txt",
            content_type=file.content_type,
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeUploadResponse(**indexed)


@app.get("/api/knowledge/documents", response_model=KnowledgeDocumentListResponse)
def list_knowledge_documents(
    limit: int = Query(50, ge=1, le=200),
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> KnowledgeDocumentListResponse:
    try:
        documents = knowledge_service.list_knowledge_documents(limit=limit)
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDocumentListResponse(
        documents=[
            KnowledgeDocumentSummary(**document)
            for document in documents
        ]
    )


@app.patch(
    "/api/knowledge/documents/{document_id}",
    response_model=KnowledgeDocumentSummary,
)
def rename_knowledge_document(
    document_id: int,
    request: KnowledgeDocumentUpdateRequest,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> KnowledgeDocumentSummary:
    try:
        document = knowledge_service.rename_knowledge_document(
            document_id,
            request.title,
        )
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDocumentSummary(**document)


@app.delete(
    "/api/knowledge/documents/{document_id}",
    response_model=KnowledgeDeleteResponse,
)
def delete_knowledge_document(
    document_id: int,
    _current_user: UserProfile = Depends(auth_service.require_knowledge_edit),
) -> KnowledgeDeleteResponse:
    try:
        knowledge_service.delete_knowledge_document(document_id)
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeDeleteResponse(ok=True)


@app.get("/api/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    _current_user: UserProfile = Depends(auth_service.require_knowledge_view),
) -> KnowledgeSearchResponse:
    try:
        results = retriever.retrieve(query, top_k=top_k)
    except Exception as error:
        _raise_http_error(error)

    return KnowledgeSearchResponse(
        query=query,
        results=[
            KnowledgeSearchResult(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                content=result.content,
                metadata=result.metadata,
                score=result.score,
            )
            for result in results
        ],
    )


@app.post("/api/project/create", response_model=ProjectCreateResponse)
async def create_project(
    name: str = Form(...),
    tender_file: UploadFile = File(...),
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectCreateResponse:
    try:
        project = project_service.create_project(
            name=name,
            file_bytes=await tender_file.read(),
            filename=tender_file.filename or "tender.txt",
            content_type=tender_file.content_type,
        )
    except Exception as error:
        _raise_http_error(error)

    return ProjectCreateResponse(
        project_id=project["id"],
        status=project["status"],
        tender_file_path=project["tender_file_path"],
    )


@app.get("/api/project/{project_id}/status", response_model=ProjectStatusResponse)
def project_status(
    project_id: int,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectStatusResponse:
    try:
        return ProjectStatusResponse(**project_service.get_project_status(project_id))
    except Exception as error:
        _raise_http_error(error)


@app.post("/api/project/{project_id}/parse", response_model=ProjectResultResponse)
def parse_project(
    project_id: int,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectResultResponse:
    try:
        project = project_service.parse_project(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectResultResponse(
        project_id=project["id"],
        status=project["status"],
        parsed_json=project["parsed_json"],
    )


@app.post(
    "/api/project/{project_id}/generate",
    response_model=ProjectGenerateResponse,
    response_model_exclude_none=True,
)
def generate_project(
    project_id: int,
    background_tasks: BackgroundTasks,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectGenerateResponse:
    try:
        task_info = generation_service.start_generation(project_id, background_tasks)
    except Exception as error:
        _raise_http_error(error)

    return ProjectGenerateResponse(
        project_id=project_id,
        status=task_info["status"],
        task_id=task_info["task_id"],
    )


@app.get("/api/project/{project_id}/download", response_model=ProjectDownloadResponse)
def download_project(
    project_id: int,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectDownloadResponse:
    try:
        download_info = project_service.get_project_download_url(project_id)
    except Exception as error:
        _raise_http_error(error)

    return ProjectDownloadResponse(**download_info)


@app.post("/api/project/{project_id}/workflow/run", response_model=WorkflowRunResponse)
def run_project_workflow(
    project_id: int,
    background_tasks: BackgroundTasks,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
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


@app.post("/api/project/{project_id}/confirm", response_model=ProjectConfirmResponse)
def confirm_project(
    project_id: int,
    request: ProjectConfirmRequest,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
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


@app.get("/api/project/{project_id}/result", response_model=ProjectResultResponse)
def project_result(
    project_id: int,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectResultResponse:
    try:
        return ProjectResultResponse(**project_service.get_project_result(project_id))
    except Exception as error:
        _raise_http_error(error)


@app.get("/api/project/{project_id}/review", response_model=ProjectReviewResponse)
def project_review(
    project_id: int,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> ProjectReviewResponse:
    try:
        return ProjectReviewResponse(**project_service.get_project_review(project_id))
    except Exception as error:
        _raise_http_error(error)


@app.get("/api/project/{project_id}/review-report")
def project_review_report(
    project_id: int,
    _current_user: UserProfile = Depends(auth_service.get_current_user),
) -> dict:
    try:
        return project_service.get_project_review_report(project_id)
    except Exception as error:
        _raise_http_error(error)
