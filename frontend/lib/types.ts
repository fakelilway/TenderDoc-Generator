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
  field?: string;
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
  bid_outline?: BidOutlineSection[];
  document_outline?: BidDocumentOutlineSection[];
  selected_chunk_ids?: number[];
  rag_references?: RagReference[];
  retrieved_chunks?: Record<string, string[]>;
  draft_markdown?: string;
  draft_volumes?: Partial<Record<DeliveryVolumeKey, string>>;
  final_checklist?: FinalChecklist | null;
  final_versions?: FinalVersion[];
  review_report?: ReviewReport | null;
  pricing_strategy?: PricingStrategy | null;
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
  duration_ms?: number | null;
  model_name?: string | null;
  fallback?: boolean;
  created_at?: string;
};

export type BidOutlineSection = {
  title: string;
  required: boolean;
  source_item?: string;
  focus_points: string[];
};

export type BidDocumentOutlineSection = {
  title: string;
  volume: string;
  section_type: string;
  required: boolean;
  source_item?: string;
  focus_points: string[];
  children: BidDocumentOutlineSection[];
};

export type RagReference = {
  section_title?: string;
  chunk_id: number;
  document_id?: number | null;
  score?: number;
  title?: string;
  snippet?: string;
  content?: string;
  metadata?: Record<string, unknown>;
};

export type FinalVersion = {
  version: number;
  markdown_path?: string | null;
  docx_path?: string | null;
};

export type FinalChecklist = {
  invalid_bid_responses?: Array<Record<string, unknown>>;
  manual_confirmation_points?: string[];
  pricing_manual_fields?: string[];
  attachment_list?: string[];
  response_matrix?: ResponseMatrix;
};

export type PricingManualField = {
  label: string;
  reason: string;
  source_text?: string;
  required: boolean;
};

export type PricingCondition = {
  name: string;
  value: string;
  risk_level: string;
  source_text?: string;
  manual_verify: boolean;
};

export type PricingStrategy = {
  project_name: string;
  project_scale: string;
  schedule_risk: string;
  payment_terms: PricingCondition[];
  competition_intensity: string;
  quote_risk: string;
  guarantee_requirements: PricingCondition[];
  manual_fields: PricingManualField[];
  extracted_conditions: PricingCondition[];
};

export type PricingStrategyReport = {
  project_name: string;
  strategy_suggestions: string[];
  risk_warnings: string[];
  commercial_response_notes: string[];
  manual_confirmation_points: string[];
  prohibited_auto_pricing: boolean;
};

export type ProjectPricingStrategyResponse = {
  project_id: number;
  pricing_strategy: PricingStrategy;
  pricing_report: PricingStrategyReport;
};

export type ScoreItemPrediction = {
  title: string;
  max_score: number;
  predicted_score: number;
  coverage_status: string;
  rationale: string;
  improvement_suggestion: string;
  location: ReviewLocation;
};

export type ScorePrediction = {
  project_name: string;
  total_max_score: number;
  predicted_total_score: number;
  score_rate: number;
  win_probability?: number | null;
  win_probability_rationale: string;
  uncertainty_notes: string[];
  strengths: string[];
  weaknesses: string[];
  items: ScoreItemPrediction[];
};

export type ProjectScorePredictionResponse = {
  project_id: number;
  score_prediction: ScorePrediction;
};

export type ResponseMatrixRow = {
  requirement_type: string;
  requirement_title: string;
  requirement_text: string;
  response_status: string;
  response_location: ReviewLocation;
  response_section: string;
  review_status: string;
  manual_confirmation_required: boolean;
  manual_confirmation_note: string;
};

export type ResponseMatrix = {
  project_id: number;
  rows: ResponseMatrixRow[];
  invalid_bid_coverage_count: number;
  total_invalid_bid_count: number;
};

export type ProjectResponseMatrixResponse = {
  project_id: number;
  response_matrix: ResponseMatrix;
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

export type ParsedConfirmationResponse = {
  project_id: number;
  status: string;
  confirmed_parsed_json: TenderRequirements;
};

export type BidOutlineResponse = {
  project_id: number;
  status: string;
  bid_outline: BidOutlineSection[];
  document_outline?: BidDocumentOutlineSection[];
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
  artifact?: string;
  artifact_label?: string;
  filename?: string;
};

export type DeliveryVolumeKey = "technical" | "commercial" | "pricing";

export type DeliveryVolumePreview = {
  key: DeliveryVolumeKey;
  label: string;
  markdown: string;
  line_count: number;
  char_count: number;
};

export type ProjectDeliveryPreviewResponse = {
  project_id: number;
  status: string;
  volumes: Record<DeliveryVolumeKey, DeliveryVolumePreview>;
};

export type DownloadArtifact =
  | "docx"
  | "pdf"
  | "markdown"
  | "review"
  | "technical_docx"
  | "commercial_docx"
  | "pricing_docx"
  | "technical_pdf"
  | "commercial_pdf"
  | "pricing_pdf";

export type ProjectSummary = {
  project_id: number;
  name: string;
  status: string;
  created_at?: string | null;
  owner_user_id?: number | null;
  owner_username?: string | null;
  owner_display_name?: string | null;
  has_download: boolean;
};

export type ProjectListResponse = {
  projects: ProjectSummary[];
};

export type ProjectDeleteResponse = {
  ok: boolean;
};

export type TemplateSummary = {
  id: number;
  name: string;
  source_filename?: string | null;
  project_type?: string | null;
  specialty?: string | null;
  envelope_type?: string | null;
  region?: string | null;
  project_year?: number | null;
  tags?: string[];
  project_name?: string | null;
  page_count?: number | null;
  created_by?: number | null;
  created_at?: string | null;
};

export type TemplateListResponse = {
  templates: TemplateSummary[];
};

export type TemplateUploadResponse = {
  template: TemplateSummary;
};

export type TemplateRecommendation = {
  template: TemplateSummary;
  match_score: number;
  match_reasons: string[];
};

export type TemplateRecommendResponse = {
  recommendations: TemplateRecommendation[];
};

export type TemplateDeleteResponse = {
  ok: boolean;
};

export type ProjectTemplateResponse = {
  project_id: number;
  template_id: number | null;
};

export type TemplateUploadPayload = {
  projectType?: string;
  specialty?: string;
  envelopeType?: string;
  region?: string;
  projectYear?: number | null;
  tags?: string[];
};

export type TemplateUpdatePayload = {
  name?: string;
  project_type?: string | null;
  specialty?: string | null;
  envelope_type?: string | null;
  region?: string | null;
  project_year?: number | null;
  tags?: string[];
};

export type KnowledgeSelectionResponse = {
  project_id: number;
  selected_chunk_ids: number[];
  references: RagReference[];
};

export type DraftMarkdownResponse = {
  project_id: number;
  status: string;
  draft_markdown: string;
  review_report?: ReviewReport | null;
};

export type FinalChecklistResponse = {
  project_id: number;
  checklist: FinalChecklist;
  versions: FinalVersion[];
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
  document_type?: string | null;
  specialty?: string | null;
  project_year?: number | null;
  tags?: string[];
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
