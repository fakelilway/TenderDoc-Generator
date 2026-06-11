import type {
  AuthMeResponse,
  BidOutlineResponse,
  BidOutlineSection,
  DraftMarkdownResponse,
  FinalChecklistResponse,
  KnowledgeDeleteResponse,
  KnowledgeDocumentListResponse,
  KnowledgeDocumentPreview,
  KnowledgeDocumentSummary,
  KnowledgeSelectionResponse,
  KnowledgeSearchResponse,
  KnowledgeUploadResponse,
  LoginResponse,
  LogoutResponse,
  ParsedConfirmationResponse,
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
  WorkflowRunResponse,
  TemplateDeleteResponse,
  TemplateListResponse,
  TemplateRecommendResponse,
  TemplateUpdatePayload,
  TemplateUploadPayload,
  TemplateUploadResponse
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
    const fallbackResponse = response.clone();
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
      }
    } catch {
      const text = await fallbackResponse.text();
      if (text) {
        message = text;
      }
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

export function createProject(
  name: string,
  file: File,
  templateId?: number | null
) {
  const body = new FormData();
  body.append("name", name);
  body.append("tender_file", file);
  if (templateId != null) {
    body.append("template_id", String(templateId));
  }
  return requestJson<ProjectCreateResponse>("/api/project/create", {
    method: "POST",
    body
  });
}

export function listTemplates() {
  return requestJson<TemplateListResponse>("/api/templates");
}

export function recommendTemplates(criteria: {
  projectType?: string;
  specialty?: string;
  envelopeType?: string;
  region?: string;
  projectYear?: number | null;
  projectName?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (criteria.projectType) params.set("project_type", criteria.projectType);
  if (criteria.specialty) params.set("specialty", criteria.specialty);
  if (criteria.envelopeType) params.set("envelope_type", criteria.envelopeType);
  if (criteria.region) params.set("region", criteria.region);
  if (criteria.projectYear != null) {
    params.set("project_year", String(criteria.projectYear));
  }
  if (criteria.projectName) params.set("project_name", criteria.projectName);
  if (criteria.limit != null) params.set("limit", String(criteria.limit));
  const query = params.toString();
  return requestJson<TemplateRecommendResponse>(
    `/api/templates/recommend${query ? `?${query}` : ""}`
  );
}

export function uploadTemplate(
  file: File,
  name: string,
  payload?: TemplateUploadPayload
) {
  const body = new FormData();
  body.append("file", file);
  body.append("name", name);
  if (payload?.projectType) body.append("project_type", payload.projectType);
  if (payload?.specialty) body.append("specialty", payload.specialty);
  if (payload?.envelopeType) body.append("envelope_type", payload.envelopeType);
  if (payload?.region) body.append("region", payload.region);
  if (payload?.projectYear != null) {
    body.append("project_year", String(payload.projectYear));
  }
  if (payload?.tags?.length) body.append("tags", payload.tags.join(","));
  return requestJson<TemplateUploadResponse>("/api/templates", {
    method: "POST",
    body
  });
}

export function updateTemplate(templateId: number, payload: TemplateUpdatePayload) {
  return requestJson<TemplateUploadResponse>(`/api/templates/${templateId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteTemplate(templateId: number) {
  return requestJson<TemplateDeleteResponse>(`/api/templates/${templateId}`, {
    method: "DELETE"
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
  outline: BidOutlineSection[]
) {
  return requestJson<BidOutlineResponse>(`/api/project/${projectId}/outline`, {
    method: "PATCH",
    body: JSON.stringify({ outline })
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

export function listKnowledgeDocuments(limit = 50) {
  return requestJson<KnowledgeDocumentListResponse>(
    `/api/knowledge/documents?limit=${limit}`
  );
}

export function getKnowledgeDocumentPreview(documentId: number) {
  return requestJson<KnowledgeDocumentPreview>(
    `/api/knowledge/documents/${documentId}/preview`
  );
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
