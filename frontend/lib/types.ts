export type SourceReference = {
  source_text?: string;
  page_number?: number | null;
};

export type RequirementItem = {
  title: string;
  description: string;
  source?: SourceReference;
};

export type TenderRequirements = {
  project_name: string;
  qualification_list: RequirementItem[];
  technical_score_items: RequirementItem[];
  invalid_bid_items: RequirementItem[];
};

export type ReviewStatus = "pass" | "fail" | "warning";

export type ReviewLocation = {
  line_number?: number | null;
  paragraph_index?: number | null;
  snippet?: string;
};

export type ReviewFinding = {
  rule: string;
  status: ReviewStatus;
  severity: "high" | "medium" | "low" | string;
  suggestion: string;
  evidence: string;
  location?: ReviewLocation;
};

export type ReviewReport = {
  findings: ReviewFinding[];
  pass_count: number;
  fail_count: number;
  warning_count: number;
  has_failures: boolean;
};

export type WorkflowState = {
  project_id: number;
  tender_text?: string;
  parsed?: TenderRequirements | null;
  retrieved_chunks?: Record<string, string[]>;
  draft_markdown?: string;
  review_report?: ReviewReport | null;
  iteration_count?: number;
  status: string;
  awaiting_human?: boolean;
  approved?: boolean;
  corrections?: Record<string, unknown>;
  trace_events?: WorkflowTraceEvent[];
};

export type WorkflowTraceEvent = {
  stage: string;
  status: "running" | "done" | "failed" | string;
  message: string;
  created_at?: string;
};

export type ProjectCreateResponse = {
  project_id: number;
  status: string;
  tender_file_path?: string | null;
};

export type ProjectStatusResponse = {
  project_id: number;
  status: string;
  parsed: boolean;
};

export type ProjectResultResponse = {
  project_id: number;
  status: string;
  parsed_json?: TenderRequirements | null;
};

export type WorkflowRunResponse = {
  project_id: number;
  status: string;
  awaiting_human: boolean;
  iteration_count: number;
  review_report?: ReviewReport | null;
};

export type ProjectReviewReportResponse = {
  project_id: number;
  status: string;
  review_report?: ReviewReport | null;
  workflow_state?: WorkflowState | null;
};

export type ProjectConfirmResponse = {
  project_id: number;
  status: string;
  approved: boolean;
  review_report?: ReviewReport | null;
};

export type ProjectDownloadResponse = {
  project_id: number;
  status: string;
  download_url: string;
  expires_in: number;
};

export type KnowledgeUploadResponse = {
  document_id: number;
  chunk_ids: number[];
  file_path: string;
};

export type KnowledgeDocumentSummary = {
  document_id: number;
  file_name: string;
  file_path?: string | null;
  file_type?: string | null;
  chunk_count: number;
  created_at: string;
};

export type KnowledgeDocumentListResponse = {
  documents: KnowledgeDocumentSummary[];
};

export type KnowledgeSearchResult = {
  chunk_id: number;
  document_id?: number | null;
  content: string;
  metadata: Record<string, unknown>;
  score: number;
};

export type KnowledgeSearchResponse = {
  query: string;
  results: KnowledgeSearchResult[];
};

export type KnowledgeDeleteResponse = {
  ok: boolean;
};

export type UserProfile = {
  id: number;
  username: string;
  display_name?: string | null;
  role: string;
  can_view_knowledge: boolean;
  can_edit_knowledge: boolean;
};

export type UserAdminProfile = UserProfile & {
  is_active: boolean;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserProfile;
};

export type AuthMeResponse = {
  user: UserProfile;
};

export type LogoutResponse = {
  ok: boolean;
};

export type UserListResponse = {
  users: UserAdminProfile[];
};

export type UserCreatePayload = {
  username: string;
  password: string;
  display_name?: string | null;
  can_view_knowledge: boolean;
  can_edit_knowledge: boolean;
};

export type RegisterPayload = {
  username: string;
  password: string;
  display_name?: string | null;
  verification_code: string;
};

export type UserPermissionsPayload = {
  display_name?: string | null;
  is_active: boolean;
  can_view_knowledge: boolean;
  can_edit_knowledge: boolean;
};

export type UserResponse = {
  user: UserAdminProfile;
};

export type RegistrationCodeResponse = {
  code: string;
  expires_at: string;
};

export type UserDeleteResponse = {
  ok: boolean;
};
