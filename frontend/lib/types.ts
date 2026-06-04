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

export type UserProfile = {
  id: number;
  username: string;
  display_name?: string | null;
  role: string;
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
