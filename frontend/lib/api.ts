import type {
  AuthMeResponse,
  BidOutlineResponse,
  BidDocumentOutlineSection,
  BidOutlineSection,
  CompanyProfile,
  CompanyProfileResponse,
  DraftMarkdownResponse,
  FinalChecklistResponse,
  KnowledgeDeleteResponse,
  KnowledgeDocumentListResponse,
  KnowledgeDocumentPreview,
  KnowledgeDocumentSummary,
  KnowledgeSelectionResponse,
  KnowledgeSearchResponse,
  ConformanceReportResponse,
  KnowledgeUploadResponse,
  PersonnelMember,
  PMRecommendationResponse,
  PMSelectionResponse,
  EvidencePagesResponse,
  PerformanceItem,
  PerformanceRecommendationResponse,
  RolePerformanceResponse,
  TechDirectorRecommendationResponse,
  LoginResponse,
  LogoutResponse,
  ParsedConfirmationResponse,
  PerformanceArchive,
  PersonArchive,
  CompanyCertArchive,
  ProjectConfirmResponse,
  ProjectCreateResponse,
  ProjectDeleteResponse,
  ProjectDeliveryPreviewResponse,
  ProjectDownloadResponse,
  DownloadArtifact,
  ProjectListResponse,
  ProjectPricingStrategyResponse,
  ProjectResponseMatrixResponse,
  ProjectResultResponse,
  ProjectReviewReportResponse,
  ProjectScorePredictionResponse,
  ProjectStatusResponse,
  RegisterPayload,
  RegistrationCodeResponse,
  UserCreatePayload,
  UserDeleteResponse,
  UserListResponse,
  UserPermissionsPayload,
  UserResponse,
  WorkflowRunResponse
} from "./types";
import { getAccessToken } from "./auth";

type ConfirmPayload = {
  approved: boolean;
  corrections?: Record<string, unknown> | null;
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...init,
    headers
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let hasServerDetail = false;
    const fallbackResponse = response.clone();
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
        hasServerDetail = true;
      }
    } catch {
      const text = await fallbackResponse.text();
      if (text) {
        message = text;
      }
    }
    if (
      !hasServerDetail &&
      (message === "500 Internal Server Error" || message === "Internal Server Error")
    ) {
      message = "后端请求中断或返回异常。任务可能仍在后台继续，请稍后刷新状态；如果状态变为失败，请查看页面保留的错误信息。";
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function login(
  username: string,
  password: string,
  accountType: "admin" | "user"
) {
  return requestJson<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, account_type: accountType })
  });
}

export function registerUser(payload: RegisterPayload) {
  return requestJson<LoginResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getCurrentUser() {
  return requestJson<AuthMeResponse>("/api/auth/me");
}

export function logout() {
  return requestJson<LogoutResponse>("/api/auth/logout", {
    method: "POST"
  });
}

export function listProjects(ownerUserId?: number | null) {
  const params = new URLSearchParams();
  if (ownerUserId != null) {
    params.set("owner_user_id", String(ownerUserId));
  }
  const query = params.toString();
  return requestJson<ProjectListResponse>(
    `/api/projects${query ? `?${query}` : ""}`
  );
}

export function deleteProject(projectId: number) {
  return requestJson<ProjectDeleteResponse>(`/api/project/${projectId}`, {
    method: "DELETE"
  });
}

export function createProject(name: string, file: File) {
  const body = new FormData();
  body.append("name", name);
  body.append("tender_file", file);
  return requestJson<ProjectCreateResponse>("/api/project/create", {
    method: "POST",
    body
  });
}

export function getProjectStatus(projectId: number) {
  return requestJson<ProjectStatusResponse>(`/api/project/${projectId}/status`);
}

export function parseProject(projectId: number) {
  return requestJson<ProjectResultResponse>(`/api/project/${projectId}/parse`, {
    method: "POST"
  });
}

export function getProjectResult(projectId: number) {
  return requestJson<ProjectResultResponse>(`/api/project/${projectId}/result`);
}

export function confirmParsedProject(
  projectId: number,
  parsedJson: Record<string, unknown>
) {
  return requestJson<ParsedConfirmationResponse>(
    `/api/project/${projectId}/parsed`,
    {
      method: "PATCH",
      body: JSON.stringify({ parsed_json: parsedJson })
    }
  );
}

export function buildProjectOutline(projectId: number) {
  return requestJson<BidOutlineResponse>(`/api/project/${projectId}/outline`, {
    method: "POST"
  });
}

export function saveProjectOutline(
  projectId: number,
  outline: BidOutlineSection[],
  documentOutline?: BidDocumentOutlineSection[]
) {
  return requestJson<BidOutlineResponse>(`/api/project/${projectId}/outline`, {
    method: "PATCH",
    body: JSON.stringify({ outline, document_outline: documentOutline })
  });
}

export function saveKnowledgeSelection(projectId: number, chunkIds: number[]) {
  return requestJson<KnowledgeSelectionResponse>(
    `/api/project/${projectId}/knowledge-selection`,
    {
      method: "PATCH",
      body: JSON.stringify({ selected_chunk_ids: chunkIds })
    }
  );
}

export function saveDraftMarkdown(projectId: number, markdown: string) {
  return requestJson<DraftMarkdownResponse>(`/api/project/${projectId}/draft`, {
    method: "PATCH",
    body: JSON.stringify({ markdown })
  });
}

export function getFinalChecklist(projectId: number) {
  return requestJson<FinalChecklistResponse>(
    `/api/project/${projectId}/final-checklist`
  );
}

export function buildProjectPricingStrategy(projectId: number) {
  return requestJson<ProjectPricingStrategyResponse>(
    `/api/project/${projectId}/pricing-strategy`,
    {
      method: "POST"
    }
  );
}

export function buildProjectScorePrediction(projectId: number) {
  return requestJson<ProjectScorePredictionResponse>(
    `/api/project/${projectId}/score-prediction`,
    {
      method: "POST"
    }
  );
}

export function buildProjectResponseMatrix(projectId: number) {
  return requestJson<ProjectResponseMatrixResponse>(
    `/api/project/${projectId}/response-matrix`,
    {
      method: "POST"
    }
  );
}

export function runProjectWorkflow(projectId: number) {
  return requestJson<WorkflowRunResponse>(
    `/api/project/${projectId}/workflow/run`,
    {
      method: "POST"
    }
  );
}

export function getProjectReviewReport(projectId: number) {
  return requestJson<ProjectReviewReportResponse>(
    `/api/project/${projectId}/review-report`
  );
}

export function confirmProject(projectId: number, payload: ConfirmPayload) {
  return requestJson<ProjectConfirmResponse>(`/api/project/${projectId}/confirm`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getProjectDownload(
  projectId: number,
  artifact: DownloadArtifact = "docx"
) {
  const params = new URLSearchParams({ artifact });
  return requestJson<ProjectDownloadResponse>(
    `/api/project/${projectId}/download?${params.toString()}`
  );
}

export function getProjectDeliveryPreview(projectId: number) {
  return requestJson<ProjectDeliveryPreviewResponse>(
    `/api/project/${projectId}/delivery-preview`
  );
}

// M23 本项目专用技术材料库:上传同类施工组织设计参考,project_id 隔离喂技术卷 RAG。
export function uploadProjectMaterial(
  projectId: number,
  file: File,
  meta?: {
    documentCategory?: string;
    specialty?: string;
    tags?: string[];
    // ② 插入图:图片会被自动识别为插入素材,target_section 指定插到技术卷哪一节
    targetSection?: string;
    caption?: string;
  }
) {
  const body = new FormData();
  body.append("file", file);
  if (meta?.documentCategory) {
    body.append("document_category", meta.documentCategory);
  }
  if (meta?.specialty) {
    body.append("specialty", meta.specialty);
  }
  if (meta?.tags?.length) {
    body.append("tags", meta.tags.join(","));
  }
  if (meta?.targetSection) {
    body.append("target_section", meta.targetSection);
  }
  if (meta?.caption) {
    body.append("caption", meta.caption);
  }
  return requestJson<KnowledgeUploadResponse>(
    `/api/project/${projectId}/material`,
    { method: "POST", body }
  );
}

export function listProjectMaterials(projectId: number) {
  return requestJson<KnowledgeDocumentListResponse>(
    `/api/project/${projectId}/material`
  );
}

// 工程量清单(另册)上传:抽全文存 projects.boq_text,驱动技术卷按真实分部分项占比定详略。
export interface ProjectBOQResponse {
  uploaded?: boolean;
  chars: number;
  total_amount_wan?: number;
  dominant?: string[];
  note?: string;
  categories?: { name: string; share_pct: number; key_quantities?: string }[];
  warning?: string;
}

export function uploadProjectBOQ(projectId: number, file: File) {
  const body = new FormData();
  body.append("file", file);
  return requestJson<ProjectBOQResponse>(`/api/project/${projectId}/boq`, {
    method: "POST",
    body
  });
}

export function getProjectBOQ(projectId: number) {
  return requestJson<ProjectBOQResponse>(`/api/project/${projectId}/boq`);
}

export function deleteProjectBOQ(projectId: number) {
  return requestJson<ProjectBOQResponse>(`/api/project/${projectId}/boq`, {
    method: "DELETE"
  });
}

// M-人员名册:项目经理选派
export function getPersonnelRecommendations(projectId: number) {
  return requestJson<PMRecommendationResponse>(
    `/api/project/${projectId}/personnel/recommendations`
  );
}

// 逐空核对报告
export function getProjectConformance(projectId: number) {
  return requestJson<ConformanceReportResponse>(
    `/api/project/${projectId}/conformance`
  );
}

export function savePersonnelSelection(
  projectId: number,
  member: PersonnelMember | null
) {
  return requestJson<PMSelectionResponse>(
    `/api/project/${projectId}/personnel`,
    { method: "PUT", body: JSON.stringify({ project_manager: member }) }
  );
}

export function getPerformanceRecommendations(projectId: number) {
  return requestJson<PerformanceRecommendationResponse>(
    `/api/project/${projectId}/performance/recommendations`
  );
}

export function savePerformanceSelection(
  projectId: number,
  selected: PerformanceItem[]
) {
  return requestJson<{ project_id: number; selected: PerformanceItem[] }>(
    `/api/project/${projectId}/performance`,
    { method: "PUT", body: JSON.stringify({ selected }) }
  );
}

// 业绩证明选页:某条业绩的全部扫描页 + 人工勾选保存(null=恢复默认规则)
export function getEvidencePages(projectId: number, name: string) {
  return requestJson<EvidencePagesResponse>(
    `/api/project/${projectId}/evidence-pages?name=${encodeURIComponent(name)}`
  );
}

export function saveEvidencePages(
  projectId: number,
  name: string,
  documentIds: number[] | null
) {
  return requestJson<{ project_id: number; name: string; selected: number[] | null }>(
    `/api/project/${projectId}/evidence-pages`,
    { method: "PUT", body: JSON.stringify({ name, document_ids: documentIds }) }
  );
}

// 角色业绩勾选:选派的项目经理(pm)/总工(td)名下业绩候选 + 人工多选保存
export function getRolePerformanceRecommendations(
  projectId: number,
  role: "pm" | "td"
) {
  return requestJson<RolePerformanceResponse>(
    `/api/project/${projectId}/role-performance/${role}/recommendations`
  );
}

export function saveRolePerformanceSelection(
  projectId: number,
  role: "pm" | "td",
  selected: PerformanceItem[]
) {
  return requestJson<{ project_id: number; role: string; selected: PerformanceItem[] }>(
    `/api/project/${projectId}/role-performance/${role}`,
    { method: "PUT", body: JSON.stringify({ selected }) }
  );
}

export function getTechDirectorRecommendations(projectId: number) {
  return requestJson<TechDirectorRecommendationResponse>(
    `/api/project/${projectId}/tech-director/recommendations`
  );
}

export function saveTechDirectorSelection(
  projectId: number,
  member: PersonnelMember | null
) {
  return requestJson<PMSelectionResponse>(
    `/api/project/${projectId}/tech-director`,
    { method: "PUT", body: JSON.stringify({ tech_director: member }) }
  );
}

export function deleteProjectMaterial(projectId: number, documentId: number) {
  return requestJson<{ ok: boolean }>(
    `/api/project/${projectId}/material/${documentId}`,
    { method: "DELETE" }
  );
}

export function uploadKnowledge(
  file: File,
  metadata?: {
    projectType?: string;
    documentType?: string;
    documentCategory?: string;
    specialty?: string;
    volume?: string;
    region?: string;
    projectYear?: number | null;
    ownerType?: string;
    ownerName?: string;
    certificateType?: string;
    validFrom?: string;
    validTo?: string;
    sensitivity?: string;
    usageScope?: string;
    verifiedStatus?: string;
    imageInsertable?: boolean | null;
    tags?: string[];
    ingestionMode?: string;
  }
) {
  const body = new FormData();
  body.append("file", file);
  if (metadata?.projectType) {
    body.append("project_type", metadata.projectType);
  }
  if (metadata?.documentType) {
    body.append("document_type", metadata.documentType);
  }
  if (metadata?.documentCategory) {
    body.append("document_category", metadata.documentCategory);
  }
  if (metadata?.specialty) {
    body.append("specialty", metadata.specialty);
  }
  if (metadata?.volume) {
    body.append("volume", metadata.volume);
  }
  if (metadata?.region) {
    body.append("region", metadata.region);
  }
  if (metadata?.projectYear) {
    body.append("project_year", String(metadata.projectYear));
  }
  if (metadata?.ownerType) {
    body.append("owner_type", metadata.ownerType);
  }
  if (metadata?.ownerName) {
    body.append("owner_name", metadata.ownerName);
  }
  if (metadata?.certificateType) {
    body.append("certificate_type", metadata.certificateType);
  }
  if (metadata?.validFrom) {
    body.append("valid_from", metadata.validFrom);
  }
  if (metadata?.validTo) {
    body.append("valid_to", metadata.validTo);
  }
  if (metadata?.sensitivity) {
    body.append("sensitivity", metadata.sensitivity);
  }
  if (metadata?.usageScope) {
    body.append("usage_scope", metadata.usageScope);
  }
  if (metadata?.verifiedStatus) {
    body.append("verified_status", metadata.verifiedStatus);
  }
  if (metadata?.imageInsertable !== undefined && metadata.imageInsertable !== null) {
    body.append("image_insertable", String(metadata.imageInsertable));
  }
  if (metadata?.tags?.length) {
    body.append("tags", metadata.tags.join(","));
  }
  if (metadata?.ingestionMode) {
    body.append("ingestion_mode", metadata.ingestionMode);
  }
  return requestJson<KnowledgeUploadResponse>("/api/knowledge/upload", {
    method: "POST",
    body
  });
}

export function renameKnowledgeDocument(
  documentId: number,
  title: string,
  metadata?: {
    projectType?: string | null;
    documentType?: string | null;
    documentCategory?: string | null;
    specialty?: string | null;
    volume?: string | null;
    region?: string | null;
    projectYear?: number | null;
    ownerType?: string | null;
    ownerName?: string | null;
    certificateType?: string | null;
    validFrom?: string | null;
    validTo?: string | null;
    sensitivity?: string | null;
    usageScope?: string | null;
    verifiedStatus?: string | null;
    imageInsertable?: boolean | null;
    tags?: string[];
  }
) {
  return requestJson<KnowledgeDocumentSummary>(
    `/api/knowledge/documents/${documentId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        title,
        project_type: metadata?.projectType ?? null,
        document_type: metadata?.documentType ?? null,
        document_category: metadata?.documentCategory ?? null,
        specialty: metadata?.specialty ?? null,
        volume: metadata?.volume ?? null,
        region: metadata?.region ?? null,
        project_year: metadata?.projectYear ?? null,
        owner_type: metadata?.ownerType ?? null,
        owner_name: metadata?.ownerName ?? null,
        certificate_type: metadata?.certificateType ?? null,
        valid_from: metadata?.validFrom ?? null,
        valid_to: metadata?.validTo ?? null,
        sensitivity: metadata?.sensitivity ?? null,
        usage_scope: metadata?.usageScope ?? null,
        verified_status: metadata?.verifiedStatus ?? null,
        image_insertable: metadata?.imageInsertable ?? null,
        tags: metadata?.tags ?? null
      })
    }
  );
}

export function deleteKnowledgeDocument(documentId: number) {
  return requestJson<KnowledgeDeleteResponse>(
    `/api/knowledge/documents/${documentId}`,
    {
      method: "DELETE"
    }
  );
}

export function listKnowledgeDocuments(
  opts: {
    limit?: number;
    category?: string;
    search?: string;
    categories?: string[];
    excludeCategories?: string[];
  } = {}
) {
  const params = new URLSearchParams();
  params.set("limit", String(opts.limit ?? 200));
  if (opts.category) {
    params.set("category", opts.category);
  }
  if (opts.search) {
    params.set("search", opts.search);
  }
  if (opts.categories?.length) {
    params.set("categories", opts.categories.join(","));
  }
  if (opts.excludeCategories?.length) {
    params.set("exclude_categories", opts.excludeCategories.join(","));
  }
  return requestJson<KnowledgeDocumentListResponse>(
    `/api/knowledge/documents?${params.toString()}`
  );
}

export function getKnowledgeCategoryCounts() {
  return requestJson<Record<string, number>>("/api/knowledge/category-counts");
}

export function getKnowledgeDocumentPreview(documentId: number) {
  return requestJson<KnowledgeDocumentPreview>(
    `/api/knowledge/documents/${documentId}/preview`
  );
}

export function getPerformanceArchive() {
  return requestJson<PerformanceArchive>("/api/performance-archive");
}

export function reassignPerformanceEvidence(
  documentIds: number[],
  targetProject: string
) {
  return requestJson<{ ok: boolean; changed: number }>(
    "/api/performance-archive/reassign",
    {
      method: "POST",
      body: JSON.stringify({ document_ids: documentIds, target_project: targetProject })
    }
  );
}

export function renamePerformanceEvidence(documentId: number, title: string) {
  return requestJson<{ ok: boolean }>(
    `/api/performance-archive/evidence/${documentId}`,
    { method: "PATCH", body: JSON.stringify({ title }) }
  );
}

export function getPersonCertArchive() {
  return requestJson<PersonArchive>("/api/cert-archive/person");
}

export function getCompanyCertArchive() {
  return requestJson<CompanyCertArchive>("/api/cert-archive/company");
}

export function reassignPersonCert(documentIds: number[], targetPerson: string) {
  return requestJson<{ ok: boolean; changed: number }>(
    "/api/cert-archive/person/reassign",
    {
      method: "POST",
      body: JSON.stringify({ document_ids: documentIds, target_person: targetPerson })
    }
  );
}

export function retypeCompanyCert(documentIds: number[], targetType: string) {
  return requestJson<{ ok: boolean; changed: number }>(
    "/api/cert-archive/company/retype",
    {
      method: "POST",
      body: JSON.stringify({ document_ids: documentIds, target_type: targetType })
    }
  );
}

export function renameCert(documentId: number, title: string) {
  return requestJson<{ ok: boolean }>(`/api/cert-archive/cert/${documentId}`, {
    method: "PATCH",
    body: JSON.stringify({ title })
  });
}

// 自助验证:下载一个把这张证件真图插好的 DOCX,亲眼确认不是只写名字。
export async function downloadCertTestDocx(documentId: number) {
  const token = getAccessToken();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`/api/cert-archive/test-insert/${documentId}`, { headers });
  if (!res.ok) {
    let message = `下载失败 ${res.status}`;
    try {
      const payload = (await res.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      /* 非 JSON 错误体,用默认提示 */
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `test_insert_${documentId}.docx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function searchKnowledge(
  query: string,
  topK = 5,
  filters?: {
    projectType?: string;
    documentType?: string;
    documentCategory?: string;
    specialty?: string;
    volume?: string;
    region?: string;
    projectYear?: number | null;
    ownerType?: string;
    ownerName?: string;
    certificateType?: string;
    sensitivity?: string;
    usageScope?: string;
    verifiedStatus?: string;
    tags?: string[];
  }
) {
  const params = new URLSearchParams({
    query,
    top_k: String(topK)
  });
  if (filters?.projectType) {
    params.set("project_type", filters.projectType);
  }
  if (filters?.documentType) {
    params.set("document_type", filters.documentType);
  }
  if (filters?.documentCategory) {
    params.set("document_category", filters.documentCategory);
  }
  if (filters?.specialty) {
    params.set("specialty", filters.specialty);
  }
  if (filters?.volume) {
    params.set("volume", filters.volume);
  }
  if (filters?.region) {
    params.set("region", filters.region);
  }
  if (filters?.projectYear) {
    params.set("project_year", String(filters.projectYear));
  }
  if (filters?.ownerType) {
    params.set("owner_type", filters.ownerType);
  }
  if (filters?.ownerName) {
    params.set("owner_name", filters.ownerName);
  }
  if (filters?.certificateType) {
    params.set("certificate_type", filters.certificateType);
  }
  if (filters?.sensitivity) {
    params.set("sensitivity", filters.sensitivity);
  }
  if (filters?.usageScope) {
    params.set("usage_scope", filters.usageScope);
  }
  if (filters?.verifiedStatus) {
    params.set("verified_status", filters.verifiedStatus);
  }
  filters?.tags?.forEach((tag) => params.append("tags", tag));
  return requestJson<KnowledgeSearchResponse>(
    `/api/knowledge/search?${params.toString()}`
  );
}

export function listUsers() {
  return requestJson<UserListResponse>("/api/admin/users");
}

export function createUser(payload: UserCreatePayload) {
  return requestJson<UserResponse>("/api/admin/users", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createRegistrationCode() {
  return requestJson<RegistrationCodeResponse>("/api/admin/registration-codes", {
    method: "POST"
  });
}

export function updateUserPermissions(
  userId: number,
  payload: UserPermissionsPayload
) {
  return requestJson<UserResponse>(`/api/admin/users/${userId}/permissions`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteUser(userId: number) {
  return requestJson<UserDeleteResponse>(`/api/admin/users/${userId}`, {
    method: "DELETE"
  });
}

export function getCompanyProfile() {
  return requestJson<CompanyProfileResponse>("/api/company-profile");
}

export function saveCompanyProfile(profile: CompanyProfile) {
  return requestJson<CompanyProfileResponse>("/api/company-profile", {
    method: "PUT",
    body: JSON.stringify(profile)
  });
}
