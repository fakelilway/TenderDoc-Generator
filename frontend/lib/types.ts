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
  tenderer_name?: string;
  project_location?: string;
  tender_scope?: string;
  planned_duration?: string;
  quality_standard?: string;
  safety_target?: string;
  bid_deadline?: string;
  bid_format_requirements?: string;
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

export type ManualImageSlot = {
  title: string;
  placement?: string;
  description?: string;
};

export type BidOutlineSection = {
  title: string;
  required: boolean;
  source_item?: string;
  focus_points: string[];
  manual_image_slots?: ManualImageSlot[];
};

export type BidDocumentOutlineSection = {
  title: string;
  volume: string;
  section_type: string;
  required: boolean;
  source_item?: string;
  focus_points: string[];
  manual_image_slots?: ManualImageSlot[];
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

// 报价卷由外部造价软件单独制作，本系统只交付商务、技术两卷。
export type DeliveryVolumeKey = "commercial" | "technical";

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
  indexing_status: string;
  extraction_message?: string;
};

export type KnowledgeDocumentSummary = {
  document_id: number;
  file_name: string;
  file_path?: string | null;
  file_type?: string | null;
  project_type?: string | null;
  document_type?: string | null;
  document_category?: string | null;
  specialty?: string | null;
  volume?: string | null;
  region?: string | null;
  project_year?: number | null;
  owner_type?: string | null;
  owner_name?: string | null;
  certificate_type?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  sensitivity?: string | null;
  usage_scope?: string | null;
  verified_status?: string | null;
  image_insertable?: boolean | null;
  tags?: string[];
  ingestion_mode?: string | null;
  indexing_status?: string | null;
  extraction_message?: string | null;
  chunk_count: number;
  created_at: string;
};

export type KnowledgeDocumentPreview = {
  document_id: number;
  file_name: string;
  file_type?: string | null;
  preview_type: "image" | "text" | "pdf" | "file" | string;
  content: string;
  preview_url?: string | null;
  download_url?: string | null;
  expires_in: number;
  indexing_status?: string | null;
  extraction_message?: string | null;
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

export type CompanyProfile = {
  company_name: string;
  credit_code: string;
  legal_representative: string;
  registered_capital: string;
  establish_date: string;
  registered_address: string;
  company_type: string;
  business_scope: string;
  qualification_grade: string;
  safety_license_no: string;
  contact_person: string;
  contact_phone: string;
  bank_name: string;
  bank_account: string;
  project_manager_name: string;
  project_manager_cert: string;
  postal_code: string;
  fax: string;
  email: string;
  legal_rep_title: string;
  legal_rep_phone: string;
  tech_director_name: string;
  tech_director_title: string;
  tech_director_phone: string;
  employee_total: string;
  project_manager_count: string;
  senior_title_count: string;
  mid_title_count: string;
  junior_title_count: string;
  technician_count: string;
  shareholders: string;
  business_term: string;
  registered_capital_words: string;
};

export type CompanyProfileResponse = {
  profile: CompanyProfile;
  updated_at: string | null;
};

// M-人员名册:本项目项目经理选派(按招标要求从公司名册推荐)
export type BuilderCert = {
  level: string;
  specialty: string;
  cert_no: string;
  valid_to: string;
};

export type PersonnelMember = {
  name: string;
  id_number: string;
  builder_certs: BuilderCert[];
  safety_cert_classes: string[];
  safety_cert_no: string;
  title: string;
  title_specialty: string;
  eight_roles: string[];
  special_works: string[];
  source: string;
};

export type PMRequirement = {
  builder_level: string;
  builder_specialty: string;
  requires_safety_b: boolean;
  note: string;
};

export type PMRecommendation = {
  member: PersonnelMember;
  score: number;
  matched: string[];
  gaps: string[];
};

export type PMRecommendationResponse = {
  project_id: number;
  requirement: PMRequirement;
  recommendations: PMRecommendation[];
  selected: PersonnelMember | null;
};

export type TechDirectorRequirement = {
  title_level: string;
  specialty: string;
  requires_registration: boolean;
  note: string;
};

export type TechDirectorRecommendationResponse = {
  project_id: number;
  requirement: TechDirectorRequirement;
  recommendations: PMRecommendation[];
  selected: PersonnelMember | null;
};

// 业绩选择(多选)
export type PerformanceRequirement = {
  since: string;
  category: string;
  min_amount_wan: number;
  min_count: number;
  time_basis: string;
};

export type PerformanceItem = {
  name: string;
  year: string;
  amount: string;
  type: string;
  document_id?: number | null;
};

export type PerformanceRecommendation = PerformanceItem & {
  manager?: string;
  has_evidence?: boolean; // 经理业绩候选无台账打分,故可选
  score?: number;
  matched: string[];
  gaps: string[];
};

export type PerformanceRecommendationResponse = {
  project_id: number;
  requirement: PerformanceRequirement;
  // 候选=员工整理的《类似项目信息表》全部记录,按招标要求打分排序;选中即原样填进投标人业绩表
  recommendations: PerformanceRecommendation[];
  selected: PerformanceItem[];
};

// 业绩证明选页(员工意见7:默认每类取前几张会截掉盖章页,人工勾选以勾选为准)
export type EvidencePageOption = {
  document_id: number;
  file_name: string;
  evidence_type: string; // 中标通知书 / 合同 / 交工验收 / 其他
  evidence_seq: number;
};

export type EvidencePagesResponse = {
  project_id: number;
  name: string;
  pages: EvidencePageOption[];
  selected: number[] | null; // null=没选过(生成走默认规则);列表=以勾选为准
  default_ids: number[]; // 默认规则会取的页(供界面预勾)
};

// 角色业绩勾选(项目经理/总工名下业绩,人工多选)
export type RolePerformanceResponse = {
  project_id: number;
  role: "pm" | "td";
  person: string | null; // 选派的人名;null=该角色尚未选派
  recommendations: PerformanceRecommendation[];
  selected: PerformanceItem[] | null; // null/[]=没勾(留白);全部人工手选
  // 信息表里当过该角色的人及条数(面板空时提示"谁有业绩可选")
  role_holders?: { name: string; count: number }[];
};

export type PMSelectionResponse = {
  project_id: number;
  selected: {
    project_manager?: PersonnelMember | null;
    tech_director?: PersonnelMember | null;
  };
};

// 逐空核对报告(读懂招标→每个空 找要求→核对→填/告警)
export type FillRequirement = {
  field: string;
  source: string;
  required: string;
  our_value: string;
  status: string; // 符合 | 不符合 | 缺料 | 待人工 | 一致 | 不一致
  action: string; // 填 | 告警 | 留空
  note: string;
};

export type ConformanceReportResponse = {
  project_id: number;
  items: FillRequirement[];
  has_blocking: boolean;
  warning_count: number;
  pending_count: number;
};

// ===== 业绩档案(台账↔证明对号整理) =====
export type PerformanceEvidenceDoc = {
  document_id: number;
  file_name: string;
  file_path?: string | null;
  evidence_type: string;
  evidence_seq: number;
};

export type PerformanceLedger = {
  document_id: number;
  file_name: string;
  name: string;
  type?: string;
  amount?: string;
  date?: string;
  year?: string;
  manager?: string;
  chief?: string;
  contract_no?: string;
};

export type PerformanceMatched = {
  evidence_project: string;
  ledger: PerformanceLedger;
  evidence: Record<string, PerformanceEvidenceDoc[]>;
  types: Record<string, number>;
  total: number;
  score: number;
  needs_review: boolean;
  complete_chain: boolean;
};

export type PerformanceEvidenceOnly = {
  evidence_project: string;
  evidence: Record<string, PerformanceEvidenceDoc[]>;
  types: Record<string, number>;
  total: number;
  best_guess: string;
  best_score: number;
};

export type PerformanceArchive = {
  matched: PerformanceMatched[];
  evidence_only: PerformanceEvidenceOnly[];
  ledger_only: PerformanceLedger[];
  ledger_all: PerformanceLedger[];
  stats: {
    ledger_total: number;
    evidence_projects: number;
    evidence_images: number;
    matched: number;
    matched_need_review: number;
    matched_complete_chain: number;
    evidence_only: number;
    ledger_only: number;
  };
};

// ===== 证件档案(人员按人归 / 公司按类型归) =====
export type CertDoc = {
  document_id: number;
  file_name: string;
  file_path?: string | null;
  cert_type: string;
};

export type PersonArchiveEntry = {
  name: string;
  total: number;
  types: Record<string, number>;
  certs: Record<string, CertDoc[]>;
};

export type PersonArchive = {
  persons: PersonArchiveEntry[];
  unassigned: CertDoc[];
  person_names: string[];
  stats: { person_count: number; cert_total: number; unassigned: number };
};

export type CompanyCertGroup = {
  cert_type: string;
  docs: CertDoc[];
  total: number;
};

export type CompanyCertArchive = {
  groups: CompanyCertGroup[];
  cert_types: string[];
  stats: { type_count: number; cert_total: number };
};
