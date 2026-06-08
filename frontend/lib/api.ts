import type {
  AuthMeResponse,
  BidOutlineResponse,
  BidOutlineSection,
  DraftMarkdownResponse,
  FinalChecklistResponse,
  KnowledgeDeleteResponse,
  KnowledgeDocumentListResponse,
  KnowledgeDocumentSummary,
  KnowledgeSelectionResponse,
  KnowledgeSearchResponse,
  KnowledgeUploadResponse,
  LoginResponse,
  LogoutResponse,
  ParsedConfirmationResponse,
  ProjectConfirmResponse,
  ProjectCreateResponse,
  ProjectDownloadResponse,
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

export function getProjectDownload(projectId: number) {
  return requestJson<ProjectDownloadResponse>(
    `/api/project/${projectId}/download`
  );
}

export function uploadKnowledge(
  file: File,
  metadata?: {
    documentType?: string;
    specialty?: string;
    projectYear?: number | null;
    tags?: string[];
  }
) {
  const body = new FormData();
  body.append("file", file);
  if (metadata?.documentType) {
    body.append("document_type", metadata.documentType);
  }
  if (metadata?.specialty) {
    body.append("specialty", metadata.specialty);
  }
  if (metadata?.projectYear) {
    body.append("project_year", String(metadata.projectYear));
  }
  if (metadata?.tags?.length) {
    body.append("tags", metadata.tags.join(","));
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
    documentType?: string | null;
    specialty?: string | null;
    projectYear?: number | null;
    tags?: string[];
  }
) {
  return requestJson<KnowledgeDocumentSummary>(
    `/api/knowledge/documents/${documentId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        title,
        document_type: metadata?.documentType ?? null,
        specialty: metadata?.specialty ?? null,
        project_year: metadata?.projectYear ?? null,
        tags: metadata?.tags ?? []
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

export function searchKnowledge(
  query: string,
  topK = 5,
  filters?: { documentType?: string; specialty?: string; tags?: string[] }
) {
  const params = new URLSearchParams({
    query,
    top_k: String(topK)
  });
  if (filters?.documentType) {
    params.set("document_type", filters.documentType);
  }
  if (filters?.specialty) {
    params.set("specialty", filters.specialty);
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
