"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  CheckCircle2,
  Download,
  FileText,
  FileStack,
  FolderOpen,
  Database,
  Loader2,
  LogOut,
  PencilLine,
  RefreshCw,
  TriangleAlert,
  Users
} from "lucide-react";
import { CorrectionModal } from "@/components/CorrectionModal";
import { DraftEditor } from "@/components/DraftEditor";
import { FinalChecklistPanel } from "@/components/FinalChecklistPanel";
import { HumanActionPrompt } from "@/components/HumanActionPrompt";
import { MarkdownPreview } from "@/components/MarkdownPreview";
import { NavLinkButton } from "@/components/NavLinkButton";
import { OutlineEditor } from "@/components/OutlineEditor";
import { ParsedReviewPanel } from "@/components/ParsedReviewPanel";
import { RagSelectionPanel } from "@/components/RagSelectionPanel";
import { RiskPanel } from "@/components/RiskPanel";
import { StatusRail } from "@/components/StatusRail";
import { StrategyPanel } from "@/components/StrategyPanel";
import { UploadPanel } from "@/components/UploadPanel";
import {
  buildProjectPricingStrategy,
  buildProjectOutline,
  buildProjectResponseMatrix,
  buildProjectScorePrediction,
  confirmParsedProject,
  confirmProject,
  createProject,
  listTemplates,
  recommendTemplates,
  getFinalChecklist,
  getProjectDeliveryPreview,
  getProjectDownload,
  getProjectReviewReport,
  getProjectResult,
  getProjectStatus,
  logout as logoutRequest,
  parseProject,
  runProjectWorkflow,
  saveDraftMarkdown,
  saveKnowledgeSelection,
  saveProjectOutline,
  searchKnowledge
} from "@/lib/api";
import { clearSession, getStoredSession } from "@/lib/auth";
import type {
  BidDocumentOutlineSection,
  BidOutlineSection,
  DeliveryVolumeKey,
  DeliveryVolumePreview,
  DownloadArtifact,
  FinalChecklist,
  FinalVersion,
  KnowledgeSearchResult,
  PricingStrategy,
  PricingStrategyReport,
  RagReference,
  ResponseMatrix,
  ReviewReport,
  ScorePrediction,
  TemplateSummary,
  TenderRequirements,
  WorkflowState
} from "@/lib/types";
import { AppLogo } from "@/components/AppLogo";

const finalStatuses = new Set([
  "approved",
  "finished",
  "generated",
  "draft_saved",
  "failed",
  "generation_failed"
]);

const runningStatuses = new Set([
  "uploading",
  "parsing",
  "processing",
  "generating",
  "reviewing"
]);

// Statuses where a draft exists and the delivery preview is worth fetching.
const previewStatuses = new Set([
  "generated",
  "reviewing",
  "human_review",
  "needs_revision",
  "draft_saved",
  "approved",
  "finished"
]);

type DirtyField = "markdown" | "parsed" | "outline" | "chunks";

function statesEqual(a: unknown, b: unknown) {
  if (Object.is(a, b)) {
    return true;
  }
  // Object.is already covers equal strings; avoid serializing large markdown.
  if (typeof a === "string" && typeof b === "string") {
    return false;
  }
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

function setStateIfChanged<T>(
  setter: Dispatch<SetStateAction<T>>,
  next: NoInfer<T>
) {
  setter((current) => (statesEqual(current, next) ? current : (next as T)));
}

function readableStatus(status: string) {
  const labels: Record<string, string> = {
    idle: "待上传",
    uploading: "上传中",
    uploaded: "已上传",
    parsing: "解析中",
    parsed: "已解析",
    parsed_confirmed: "解析已确认",
    outline_ready: "大纲待确认",
    outline_confirmed: "大纲已确认",
    outline_review: "待确认大纲",
    processing: "处理中",
    generating: "生成中",
    generated: "已生成",
    reviewing: "审查中",
    human_review: "待确认",
    draft_saved: "草稿已保存",
    needs_revision: "待修正",
    approved: "已批准",
    finished: "已完成",
    failed: "失败",
    generation_failed: "生成失败"
  };
  return labels[status] ?? status;
}

function nextStepCopy(status: string, hasProject: boolean) {
  if (!hasProject) {
    return "先填写项目名称并上传招标文件，系统会自动进入解析。";
  }
  const copy: Record<string, string> = {
    uploaded: "下一步：解析招标文件，确认项目名称、招标人、工期、质量标准等字段。",
    parsing: "正在解析招标文件，请等待结构化结果出现。",
    parsed: "下一步：检查解析字段，确认无误后生成标书目录。",
    parsed_confirmed: "下一步：生成并确认商务、技术、报价目录。",
    outline_ready: "下一步：检查目录结构，必要时调整后保存。",
    outline_review: "下一步：确认解析结果和目录，然后开始生成。",
    outline_confirmed: "下一步：点击“开始生成”，系统会调用大模型生成完整标书。",
    processing: "正在准备生成上下文，系统会读取模板、知识库和招标文件。",
    generating: "正在调用大模型生成标书。长文档会停留较久，请看实时状态。",
    reviewing: "正在审查废标风险和响应完整性。",
    human_review: "下一步：人工检查正文，必要时修改，然后批准并导出。",
    needs_revision: "下一步：根据审查意见修改正文，再重新确认。",
    approved: "标书已确认，可以下载 DOCX、PDF 或审查报告。",
    finished: "标书已完成，可以下载并进入新点制作软件封装。",
    generated: "标书已生成，可以预览、编辑并下载。",
    failed: "任务失败，请查看实时状态中的失败原因。",
    generation_failed: "生成失败，请检查模型 API、网络或重试。"
  };
  return copy[status] ?? "按左侧流程从上到下完成上传、解析、选资料、生成、审查和下载。";
}

function errorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function triggerDownload(url: string, filename?: string) {
  const link = document.createElement("a");
  link.href = url;
  if (filename) {
    link.download = filename;
  }
  link.rel = "noopener noreferrer";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

type DeliveryMode = "combined" | "split";
type DeliveryFormat = "docx" | "pdf";

const deliveryVolumes: Array<{
  key: DeliveryVolumeKey;
  label: string;
}> = [
  { key: "commercial", label: "商务文件" },
  { key: "technical", label: "技术文件" },
  { key: "pricing", label: "报价文件" }
];

function deliveryArtifact(
  mode: DeliveryMode,
  format: DeliveryFormat,
  volume?: DeliveryVolumeKey
): DownloadArtifact {
  if (mode === "combined") {
    return format;
  }
  return `${volume}_${format}` as DownloadArtifact;
}

function volumePreviewFromDrafts(
  drafts?: Partial<Record<DeliveryVolumeKey, string>>
) {
  if (!drafts) {
    return null;
  }
  return deliveryVolumes.reduce(
    (acc, volume) => {
      const markdown = drafts[volume.key] || "";
      acc[volume.key] = {
        key: volume.key,
        label: volume.label,
        markdown,
        line_count: markdown ? markdown.split("\n").length : 0,
        char_count: markdown.length
      };
      return acc;
    },
    {} as Record<DeliveryVolumeKey, DeliveryVolumePreview>
  );
}

export function TenderWorkspace({
  initialProjectId = null
}: {
  initialProjectId?: number | null;
}) {
  const [projectName, setProjectName] = useState("演示技术标项目");
  const [file, setFile] = useState<File | null>(null);
  const [projectId, setProjectId] = useState<number | null>(initialProjectId);
  const [status, setStatus] = useState("idle");
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewReport, setReviewReport] = useState<ReviewReport | null>(null);
  const [workflowState, setWorkflowState] = useState<WorkflowState | null>(null);
  const [parsedJson, setParsedJson] = useState<TenderRequirements | null>(null);
  const [parsedJsonText, setParsedJsonText] = useState("");
  const [outline, setOutline] = useState<BidOutlineSection[]>([]);
  const [documentOutline, setDocumentOutline] = useState<BidDocumentOutlineSection[]>(
    []
  );
  const [ragQuery, setRagQuery] = useState("施工组织设计 技术标 模板");
  const [ragProjectType, setRagProjectType] = useState("");
  const [ragDocumentType, setRagDocumentType] = useState("");
  const [ragDocumentCategory, setRagDocumentCategory] = useState("");
  const [ragSpecialty, setRagSpecialty] = useState("");
  const [ragVolume, setRagVolume] = useState("");
  const [ragRegion, setRagRegion] = useState("");
  const [ragCertificateType, setRagCertificateType] = useState("");
  const [ragUsageScope, setRagUsageScope] = useState("");
  const [ragVerifiedStatus, setRagVerifiedStatus] = useState("");
  const [ragTagText, setRagTagText] = useState("");
  const [ragResults, setRagResults] = useState<KnowledgeSearchResult[]>([]);
  const [selectedChunkIds, setSelectedChunkIds] = useState<number[]>([]);
  const [ragReferences, setRagReferences] = useState<RagReference[]>([]);
  const [finalChecklist, setFinalChecklist] = useState<FinalChecklist | null>(null);
  const [finalVersions, setFinalVersions] = useState<FinalVersion[]>([]);
  const [pricingStrategy, setPricingStrategy] = useState<PricingStrategy | null>(null);
  const [pricingReport, setPricingReport] = useState<PricingStrategyReport | null>(null);
  const [scorePrediction, setScorePrediction] = useState<ScorePrediction | null>(null);
  const [responseMatrix, setResponseMatrix] = useState<ResponseMatrix | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [activeLine, setActiveLine] = useState<number | null>(null);
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>("combined");
  const [deliveryFormat, setDeliveryFormat] = useState<DeliveryFormat>("docx");
  const [activeDeliveryVolume, setActiveDeliveryVolume] =
    useState<DeliveryVolumeKey>("commercial");
  const [deliveryPreview, setDeliveryPreview] = useState<
    Record<DeliveryVolumeKey, DeliveryVolumePreview> | null
  >(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [humanPromptOpen, setHumanPromptOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null);
  const [recommendedTemplateId, setRecommendedTemplateId] = useState<number | null>(
    null
  );
  const autoStartedWorkflowProject = useRef<number | null>(null);
  const lastHumanPromptKey = useRef("");
  const autoAnalysisTriggered = useRef<Set<string>>(new Set());
  // Fields with unsaved local edits; polling must not overwrite these.
  const dirtyFields = useRef<Set<DirtyField>>(new Set());
  // Guards against stale/out-of-order refresh responses after project switches.
  const projectIdRef = useRef<number | null>(initialProjectId);
  const refreshSeq = useRef(0);
  // Last status applied by refreshProject, for detecting preview transitions.
  const lastRefreshedStatus = useRef<string | null>(null);

  const canConfirm = Boolean(projectId && workflowState?.awaiting_human);
  const canStartWorkflow = Boolean(
    projectId && ["outline_confirmed", "outline_review"].includes(status)
  );
  const canDownload = Boolean(
    projectId && ["approved", "finished", "generated"].includes(status)
  );
  const statusText = useMemo(() => readableStatus(status), [status]);
  const nextStepText = useMemo(
    () => nextStepCopy(status, Boolean(projectId)),
    [projectId, status]
  );
  const statusBusy = busy || actionBusy || runningStatuses.has(status);
  const applyWorkflowSnapshot = useCallback(
    (state?: WorkflowState | null, report?: ReviewReport | null) => {
      if (state) {
        setStateIfChanged(setWorkflowState, state);
        if (state.status) {
          setStatus(state.status);
        }
        if (state.draft_markdown && !dirtyFields.current.has("markdown")) {
          setStateIfChanged(setMarkdown, state.draft_markdown);
        }
        if (state.draft_volumes && !dirtyFields.current.has("markdown")) {
          setStateIfChanged(
            setDeliveryPreview,
            volumePreviewFromDrafts(state.draft_volumes)
          );
        }
        if (state.parsed && !dirtyFields.current.has("parsed")) {
          setStateIfChanged(setParsedJson, state.parsed);
          setStateIfChanged(
            setParsedJsonText,
            JSON.stringify(state.parsed, null, 2)
          );
        }
        if (state.bid_outline && !dirtyFields.current.has("outline")) {
          setStateIfChanged(setOutline, state.bid_outline);
        }
        if (state.document_outline) {
          setStateIfChanged(setDocumentOutline, state.document_outline);
        }
        if (state.selected_chunk_ids && !dirtyFields.current.has("chunks")) {
          setStateIfChanged(setSelectedChunkIds, state.selected_chunk_ids);
        }
        if (state.rag_references) {
          setStateIfChanged(setRagReferences, state.rag_references);
        }
        if (state.final_checklist) {
          setStateIfChanged(setFinalChecklist, state.final_checklist);
          if (state.final_checklist.response_matrix) {
            setStateIfChanged(
              setResponseMatrix,
              state.final_checklist.response_matrix
            );
          }
        }
        if (state.final_versions) {
          setStateIfChanged(setFinalVersions, state.final_versions);
        }
        if (state.review_report) {
          setStateIfChanged(setReviewReport, state.review_report);
        }
        if (state.pricing_strategy) {
          setStateIfChanged(
            setPricingStrategy,
            state.pricing_strategy as PricingStrategy
          );
        }
      }
      if (report) {
        setStateIfChanged(setReviewReport, report);
      }
    },
    []
  );

  const refreshDeliveryPreview = useCallback(async (id: number) => {
    try {
      const preview = await getProjectDeliveryPreview(id);
      // Drop stale responses, and never overwrite a preview that reflects
      // fresher local markdown edits.
      if (projectIdRef.current !== id || dirtyFields.current.has("markdown")) {
        return;
      }
      setStateIfChanged(setDeliveryPreview, preview.volumes);
    } catch {
      // Keep the previous preview on transient fetch failures.
    }
  }, []);

  const refreshProject = useCallback(
    async (id: number, silent = false) => {
      const seq = ++refreshSeq.current;
      const isStale = () =>
        projectIdRef.current !== id || refreshSeq.current !== seq;
      try {
        const projectStatus = await getProjectStatus(id);
        if (isStale()) {
          return;
        }
        setStatus(projectStatus.status);
        if (projectStatus.parsed && !dirtyFields.current.has("parsed")) {
          const result = await getProjectResult(id);
          if (isStale()) {
            return;
          }
          if (result.parsed_json && !dirtyFields.current.has("parsed")) {
            setStateIfChanged(setParsedJson, result.parsed_json);
            setStateIfChanged(
              setParsedJsonText,
              JSON.stringify(result.parsed_json, null, 2)
            );
          }
        }

        const reviewSnapshot = await getProjectReviewReport(id);
        if (isStale()) {
          return;
        }
        const nextStatus =
          reviewSnapshot.workflow_state?.status || reviewSnapshot.status;
        const previousStatus = lastRefreshedStatus.current;
        lastRefreshedStatus.current = nextStatus;
        setStatus(nextStatus);
        applyWorkflowSnapshot(
          reviewSnapshot.workflow_state,
          reviewSnapshot.review_report
        );
        // Fetch the delivery preview only when transitioning into a
        // preview-relevant status, not on every poll tick.
        if (
          reviewSnapshot.workflow_state?.draft_markdown &&
          previewStatuses.has(nextStatus) &&
          !previewStatuses.has(previousStatus ?? "")
        ) {
          await refreshDeliveryPreview(id);
        }
      } catch (refreshError) {
        if (!silent && !isStale()) {
          setError(errorMessage(refreshError));
        }
      }
    },
    [applyWorkflowSnapshot, refreshDeliveryPreview]
  );

  const startWorkflow = useCallback(
    async (id: number) => {
      setActionBusy(true);
      setError(null);
      try {
        setStatus("processing");
        const workflow = await runProjectWorkflow(id);
        setStatus(workflow.status);
        setWorkflowState({
          project_id: workflow.project_id,
          status: workflow.status,
          awaiting_human: workflow.awaiting_human,
          iteration_count: workflow.iteration_count,
          review_report: workflow.review_report ?? null
        });
        if (workflow.review_report) {
          setReviewReport(workflow.review_report);
        }
        await refreshProject(id, true);
        await refreshDeliveryPreview(id);
      } catch (workflowError) {
        autoStartedWorkflowProject.current = null;
        setStatus("failed");
        setError(errorMessage(workflowError));
      } finally {
        setActionBusy(false);
      }
    },
    [refreshDeliveryPreview, refreshProject]
  );

  const handleApprove = useCallback(async () => {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const confirmed = await confirmProject(projectId, {
        approved: true,
        corrections: null
      });
      setStatus(confirmed.status);
      if (confirmed.review_report) {
        setReviewReport(confirmed.review_report);
      }
      await refreshProject(projectId);
      await refreshDeliveryPreview(projectId);
    } catch (approveError) {
      setError(errorMessage(approveError));
    } finally {
      setActionBusy(false);
    }
  }, [projectId, refreshDeliveryPreview, refreshProject]);

  const humanActionPrompt = useMemo(
    () => buildHumanActionPrompt(status, {
      canStartWorkflow,
      canConfirm,
      actionBusy,
      onClose: () => setHumanPromptOpen(false),
      onStartWorkflow: () => {
        setHumanPromptOpen(false);
        if (projectId) {
          void startWorkflow(projectId);
        }
      },
      onOpenCorrection: () => {
        setHumanPromptOpen(false);
        setModalOpen(true);
      },
      onApprove: () => {
        setHumanPromptOpen(false);
        void handleApprove();
      }
    }),
    [actionBusy, canConfirm, canStartWorkflow, projectId, status, startWorkflow, handleApprove]
  );

  useEffect(() => {
    if (initialProjectId) {
      void refreshProject(initialProjectId);
    }
  }, [initialProjectId, refreshProject]);

  useEffect(() => {
    if (projectId && canDownload) {
      void refreshDeliveryPreview(projectId);
    }
  }, [canDownload, projectId, refreshDeliveryPreview]);

  useEffect(() => {
    const session = getStoredSession();
    setUsername(session?.displayName || session?.username || "");
    setIsAdmin(session?.role === "admin");
  }, []);

  useEffect(() => {
    if (initialProjectId) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const response = await listTemplates();
        if (cancelled) return;
        setTemplates(response.templates);
        if (response.templates.length && projectName.trim()) {
          const recommendation = await recommendTemplates({
            projectName: projectName.trim(),
            limit: 1
          });
          if (cancelled) return;
          const top = recommendation.recommendations[0];
          if (top && top.match_score > 0) {
            setRecommendedTemplateId(top.template.id);
            setSelectedTemplateId((current) => current ?? top.template.id);
          }
        }
      } catch {
        // Template recommendation is best-effort; ignore failures.
      }
    })();
    return () => {
      cancelled = true;
    };
    // Only run when entering the blank workspace (new project flow).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialProjectId]);

  useEffect(() => {
    if (!projectId || finalStatuses.has(status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshProject(projectId, true);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [projectId, refreshProject, status]);

  useEffect(() => {
    if (!projectId) {
      lastHumanPromptKey.current = "";
      return;
    }
    if (!humanActionPrompt) {
      lastHumanPromptKey.current = "";
      return;
    }
    const promptKey = `${projectId}:${status}`;
    if (lastHumanPromptKey.current === promptKey) {
      return;
    }
    lastHumanPromptKey.current = promptKey;
    setHumanPromptOpen(true);
  }, [humanActionPrompt, projectId, status]);

  // Auto-trigger pricing / score / matrix analyses once workflow produces a draft.
  useEffect(() => {
    if (!projectId) return;
    const triggerStatuses = new Set([
      "human_review",
      "approved",
      "finished",
      "generated",
    ]);
    if (!triggerStatuses.has(status)) return;
    const key = `${projectId}:${status}`;
    if (autoAnalysisTriggered.current.has(key)) return;
    autoAnalysisTriggered.current.add(key);

    buildProjectPricingStrategy(projectId)
      .then((r) => {
        setPricingStrategy(r.pricing_strategy);
        setPricingReport(r.pricing_report);
      })
      .catch(() => {});

    buildProjectScorePrediction(projectId)
      .then((r) => setScorePrediction(r.score_prediction))
      .catch(() => {});

    buildProjectResponseMatrix(projectId)
      .then((r) => setResponseMatrix(r.response_matrix))
      .catch(() => {});
  }, [projectId, status]);

  function handleParsedJsonTextChange(value: string) {
    dirtyFields.current.add("parsed");
    setParsedJsonText(value);
  }

  function handleOutlineChange(next: BidOutlineSection[]) {
    dirtyFields.current.add("outline");
    setOutline(next);
  }

  function handleMarkdownChange(value: string) {
    dirtyFields.current.add("markdown");
    setMarkdown(value);
  }

  function handleFileChange(nextFile: File | null) {
    setFile(nextFile);
    if (nextFile && (!projectName.trim() || projectName === "演示技术标项目")) {
      setProjectName(nextFile.name.replace(/\.[^.]+$/, ""));
    }
  }

  async function handleCreateAndRun() {
    if (!file || !projectName.trim()) {
      return;
    }

    setBusy(true);
    setError(null);
    setReviewReport(null);
    setWorkflowState(null);
    setParsedJson(null);
    setParsedJsonText("");
    setOutline([]);
    setDocumentOutline([]);
    setRagResults([]);
    setSelectedChunkIds([]);
    setRagReferences([]);
    setFinalChecklist(null);
    setFinalVersions([]);
    setPricingStrategy(null);
    setPricingReport(null);
    setScorePrediction(null);
    setResponseMatrix(null);
    setMarkdown("");
    setDeliveryPreview(null);
    setHumanPromptOpen(false);
    lastHumanPromptKey.current = "";
    autoStartedWorkflowProject.current = null;
    autoAnalysisTriggered.current = new Set();
    dirtyFields.current = new Set();
    lastRefreshedStatus.current = null;
    // Invalidate any in-flight refresh for the previous project.
    projectIdRef.current = null;
    refreshSeq.current += 1;
    setActiveLine(null);

    try {
      setStatus("uploading");
      const created = await createProject(
        projectName.trim(),
        file,
        selectedTemplateId
      );
      projectIdRef.current = created.project_id;
      setProjectId(created.project_id);
      window.history.pushState(null, "", `/project/${created.project_id}`);
      setStatus(created.status);

      setStatus("parsing");
      const parsed = await parseProject(created.project_id);
      setStatus(parsed.status);
      if (parsed.parsed_json) {
        setParsedJson(parsed.parsed_json);
        setParsedJsonText(JSON.stringify(parsed.parsed_json, null, 2));
      }
    } catch (runError) {
      setStatus("failed");
      setError(errorMessage(runError));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmParsed() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(parsedJsonText) as Record<string, unknown>;
      const confirmed = await confirmParsedProject(projectId, parsed);
      dirtyFields.current.delete("parsed");
      setStatus(confirmed.status);
      setParsedJson(confirmed.confirmed_parsed_json);
      setParsedJsonText(JSON.stringify(confirmed.confirmed_parsed_json, null, 2));
      const built = await buildProjectOutline(projectId);
      dirtyFields.current.delete("outline");
      setStatus(built.status);
      setOutline(built.bid_outline);
      setDocumentOutline(built.document_outline ?? []);
    } catch (confirmError) {
      setError(errorMessage(confirmError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleBuildOutline() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const built = await buildProjectOutline(projectId);
      dirtyFields.current.delete("outline");
      setStatus(built.status);
      setOutline(built.bid_outline);
      setDocumentOutline(built.document_outline ?? []);
    } catch (outlineError) {
      setError(errorMessage(outlineError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleSaveOutline() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const saved = await saveProjectOutline(projectId, outline);
      dirtyFields.current.delete("outline");
      setStatus(saved.status);
      setOutline(saved.bid_outline);
      setDocumentOutline(saved.document_outline ?? []);
    } catch (outlineError) {
      setError(errorMessage(outlineError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleSearchKnowledge() {
    setActionBusy(true);
    setError(null);
    try {
      const tags = ragTagText
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean);
      const response = await searchKnowledge(ragQuery, 8, {
        projectType: ragProjectType.trim() || undefined,
        documentType: ragDocumentType.trim() || undefined,
        documentCategory: ragDocumentCategory.trim() || undefined,
        specialty: ragSpecialty.trim() || undefined,
        volume: ragVolume.trim() || undefined,
        region: ragRegion.trim() || undefined,
        certificateType: ragCertificateType.trim() || undefined,
        usageScope: ragUsageScope.trim() || undefined,
        verifiedStatus: ragVerifiedStatus.trim() || undefined,
        tags
      });
      setRagResults(response.results);
    } catch (searchError) {
      setError(errorMessage(searchError));
    } finally {
      setActionBusy(false);
    }
  }

  function handleToggleChunk(chunkId: number) {
    dirtyFields.current.add("chunks");
    setSelectedChunkIds((current) =>
      current.includes(chunkId)
        ? current.filter((id) => id !== chunkId)
        : [...current, chunkId]
    );
  }

  async function handleSaveKnowledgeSelection() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const saved = await saveKnowledgeSelection(projectId, selectedChunkIds);
      dirtyFields.current.delete("chunks");
      setSelectedChunkIds(saved.selected_chunk_ids);
      setRagReferences(saved.references);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleSaveDraft() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const saved = await saveDraftMarkdown(projectId, markdown);
      dirtyFields.current.delete("markdown");
      setStatus(saved.status);
      setMarkdown(saved.draft_markdown);
      if (saved.review_report) {
        setReviewReport(saved.review_report);
      }
      await refreshDeliveryPreview(projectId);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleFinalChecklist() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const result = await getFinalChecklist(projectId);
      setFinalChecklist(result.checklist);
      setFinalVersions(result.versions);
      if (result.checklist.response_matrix) {
        setResponseMatrix(result.checklist.response_matrix);
      }
    } catch (checklistError) {
      setError(errorMessage(checklistError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleBuildPricingStrategy() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const result = await buildProjectPricingStrategy(projectId);
      setPricingStrategy(result.pricing_strategy);
      setPricingReport(result.pricing_report);
    } catch (strategyError) {
      setError(errorMessage(strategyError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleBuildScorePrediction() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const result = await buildProjectScorePrediction(projectId);
      setScorePrediction(result.score_prediction);
    } catch (scoreError) {
      setError(errorMessage(scoreError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleBuildResponseMatrix() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const result = await buildProjectResponseMatrix(projectId);
      setResponseMatrix(result.response_matrix);
    } catch (matrixError) {
      setError(errorMessage(matrixError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleRefresh() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      await refreshProject(projectId);
    } finally {
      setActionBusy(false);
    }
  }

  async function handleCorrectionSubmit(approved: boolean, note: string) {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const corrections = note.trim() ? { note: note.trim() } : {};
      const confirmed = await confirmProject(projectId, {
        approved,
        corrections
      });
      setStatus(confirmed.status);
      if (confirmed.review_report) {
        setReviewReport(confirmed.review_report);
      }
      setModalOpen(false);
      await refreshProject(projectId);
    } catch (correctionError) {
      setError(errorMessage(correctionError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleDownload(
    artifact: DownloadArtifact = "docx"
  ) {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      // A fresh presigned URL is generated on every request, so an expired
      // link can always be recovered by clicking again.
      const result = await getProjectDownload(projectId, artifact);
      triggerDownload(result.download_url, result.filename);
    } catch (downloadError) {
      setError(errorMessage(downloadError));
    } finally {
      setActionBusy(false);
    }
  }

  async function handleLogout() {
    try {
      await logoutRequest();
    } catch {
      // Local logout should still proceed if the token has already expired.
    }
    clearSession();
    window.location.replace("/login");
  }

  return (
    <main className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-white/90 shadow-sm backdrop-blur-xl">
        <div className="flex min-h-16 flex-col gap-3 px-4 py-3 lg:px-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <AppLogo className="h-10 w-10 border border-line shadow-sm" />
                <div>
                  <h1 className="text-lg font-semibold text-ink">
                    TenderDoc Generator
                  </h1>
                  <p className="text-xs text-muted">
                    Project {projectId ?? "-"} · {nextStepText}
                  </p>
                </div>
              </div>
            </div>

            <nav className="flex flex-wrap items-center gap-2">
              {username ? (
                <span className="inline-flex h-9 items-center rounded-full border border-line bg-field px-3 text-sm font-medium text-muted">
                  {username}
                </span>
              ) : null}
              <NavLinkButton href="/projects" icon={FolderOpen}>
                历史项目
              </NavLinkButton>
              <NavLinkButton href="/knowledge" icon={Database}>
                知识库
              </NavLinkButton>
              {isAdmin ? (
                <>
                  <NavLinkButton href="/templates" icon={FileStack}>
                    模板库
                  </NavLinkButton>
                  <NavLinkButton href="/admin/users" icon={Users}>
                    账号管理
                  </NavLinkButton>
                </>
              ) : null}
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-full border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
                onClick={handleLogout}
              >
                <LogOut className="h-4 w-4" />
                退出
              </button>
            </nav>
          </div>

          <div className="flex flex-col gap-3 rounded-2xl border border-line bg-field/80 p-2 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2 px-1 text-xs text-muted">
              <span className="rounded-full border border-line bg-white px-3 py-1.5 font-semibold text-ink">
                {statusText}
              </span>
              <span>{statusBusy ? "任务运行中" : "等待操作"}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={!projectId || actionBusy}
                className="inline-flex h-9 items-center gap-2 rounded-full border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field disabled:cursor-not-allowed disabled:text-muted"
                onClick={handleRefresh}
              >
                {actionBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                刷新状态
              </button>
              <button
                type="button"
                disabled={!canStartWorkflow || actionBusy}
                className="inline-flex h-9 items-center gap-2 rounded-full bg-ink px-4 text-sm font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:bg-slate-300"
                onClick={() => projectId && startWorkflow(projectId)}
              >
                <Loader2 className={actionBusy ? "h-4 w-4 animate-spin" : "hidden"} />
                开始生成
              </button>
              <button
                type="button"
                disabled={!canConfirm || actionBusy}
                className="inline-flex h-9 items-center gap-2 rounded-full border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field disabled:cursor-not-allowed disabled:text-muted"
                onClick={() => setModalOpen(true)}
              >
                <PencilLine className="h-4 w-4" />
                修改意见
              </button>
              <button
                type="button"
                disabled={!canConfirm || actionBusy}
                className="inline-flex h-9 items-center gap-2 rounded-full bg-ok px-4 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-green-300"
                onClick={handleApprove}
              >
                <CheckCircle2 className="h-4 w-4" />
                确认导出
              </button>
              <button
                type="button"
                disabled={!canDownload || actionBusy}
                className="inline-flex h-9 items-center gap-2 rounded-full bg-brand px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
                onClick={() => handleDownload("docx")}
              >
                <Download className="h-4 w-4" />
                下载标书
              </button>
            </div>
          </div>
        </div>
      </header>

      {error ? (
        <div className="mx-4 mt-4 flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-danger lg:mx-6">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <p>{error}</p>
        </div>
      ) : null}

      {canDownload ? (
        <div className="mx-4 mt-4 flex flex-col gap-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-ok lg:mx-6">
          <div className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="font-semibold">标书已完成，可按投递网站要求下载</p>
              <p className="text-xs text-green-700">
                合并文件顺序固定为商务文件、技术文件、报价文件；也可按分卷分别投递。
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-md border border-green-300 bg-white p-1">
                {(["combined", "split"] as DeliveryMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setDeliveryMode(mode)}
                    className={[
                      "h-8 rounded px-3 text-xs font-semibold transition",
                      deliveryMode === mode
                        ? "bg-ok text-white"
                        : "text-ok hover:bg-green-50"
                    ].join(" ")}
                  >
                    {mode === "combined" ? "合并投递" : "分开投递"}
                  </button>
                ))}
              </div>
              <div className="inline-flex rounded-md border border-green-300 bg-white p-1">
                {(["docx", "pdf"] as DeliveryFormat[]).map((format) => (
                  <button
                    key={format}
                    type="button"
                    onClick={() => setDeliveryFormat(format)}
                    className={[
                      "h-8 rounded px-3 text-xs font-semibold uppercase transition",
                      deliveryFormat === format
                        ? "bg-ok text-white"
                        : "text-ok hover:bg-green-50"
                    ].join(" ")}
                  >
                    {format}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {deliveryMode === "combined" ? (
                <button
                  type="button"
                  disabled={actionBusy}
                  onClick={() =>
                    handleDownload(deliveryArtifact("combined", deliveryFormat))
                  }
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-ok px-3 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-green-300"
                >
                  <Download className="h-4 w-4" />
                  合并{deliveryFormat.toUpperCase()}
                </button>
              ) : (
                deliveryVolumes.map((volume) => (
                  <button
                    key={volume.key}
                    type="button"
                    disabled={actionBusy}
                    onClick={() =>
                      handleDownload(
                        deliveryArtifact("split", deliveryFormat, volume.key)
                      )
                    }
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-ok px-3 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-green-300"
                  >
                    <Download className="h-4 w-4" />
                    {volume.label}
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-green-200 pt-3">
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => handleDownload("docx")}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-green-300 bg-white px-3 text-sm font-medium text-ok hover:bg-green-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              原始DOCX
            </button>
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => handleDownload("markdown")}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-green-300 bg-white px-3 text-sm font-medium text-ok hover:bg-green-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              Markdown
            </button>
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => handleDownload("review")}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-green-300 bg-white px-3 text-sm font-medium text-ok hover:bg-green-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              审查报告
            </button>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 p-4 lg:grid-cols-[320px_minmax(0,1fr)_360px] lg:p-6">
        <div className="space-y-4">
          <UploadPanel
            projectName={projectName}
            file={file}
            busy={busy}
            templates={templates}
            selectedTemplateId={selectedTemplateId}
            recommendedTemplateId={recommendedTemplateId}
            onProjectNameChange={setProjectName}
            onFileChange={handleFileChange}
            onTemplateChange={setSelectedTemplateId}
            onSubmit={handleCreateAndRun}
          />
          <RagSelectionPanel
            query={ragQuery}
            projectType={ragProjectType}
            documentType={ragDocumentType}
            documentCategory={ragDocumentCategory}
            specialty={ragSpecialty}
            volume={ragVolume}
            region={ragRegion}
            certificateType={ragCertificateType}
            usageScope={ragUsageScope}
            verifiedStatus={ragVerifiedStatus}
            tagText={ragTagText}
            results={ragResults}
            selectedIds={selectedChunkIds}
            references={ragReferences}
            busy={actionBusy}
            onQueryChange={setRagQuery}
            onProjectTypeChange={setRagProjectType}
            onDocumentTypeChange={setRagDocumentType}
            onDocumentCategoryChange={setRagDocumentCategory}
            onSpecialtyChange={setRagSpecialty}
            onVolumeChange={setRagVolume}
            onRegionChange={setRagRegion}
            onCertificateTypeChange={setRagCertificateType}
            onUsageScopeChange={setRagUsageScope}
            onVerifiedStatusChange={setRagVerifiedStatus}
            onTagTextChange={setRagTagText}
            onSearch={handleSearchKnowledge}
            onToggle={handleToggleChunk}
            onSave={handleSaveKnowledgeSelection}
          />
          <StatusRail
            status={status}
            busy={statusBusy}
            traceEvents={workflowState?.trace_events}
          />
        </div>

        <div className="space-y-4">
          <ParsedReviewPanel
            parsed={parsedJson}
            value={parsedJsonText}
            busy={actionBusy}
            onChange={handleParsedJsonTextChange}
            onSave={handleConfirmParsed}
          />
          <OutlineEditor
            outline={outline}
            documentOutline={documentOutline}
            busy={actionBusy}
            onChange={handleOutlineChange}
            onBuild={handleBuildOutline}
            onSave={handleSaveOutline}
          />
          <DraftEditor
            markdown={markdown}
            busy={actionBusy}
            onChange={handleMarkdownChange}
            onSave={handleSaveDraft}
            onChecklist={handleFinalChecklist}
          />
          <MarkdownPreview markdown={markdown} activeLine={activeLine} />
        </div>

        <div className="space-y-4">
          <DeliveryVolumePanel
            volumes={deliveryPreview}
            activeVolume={activeDeliveryVolume}
            onActiveVolumeChange={setActiveDeliveryVolume}
          />
          <RiskPanel
            report={reviewReport}
            activeLine={activeLine}
            onSelect={setActiveLine}
          />
          <FinalChecklistPanel
            checklist={finalChecklist}
            versions={finalVersions}
          />
          <StrategyPanel
            pricingStrategy={pricingStrategy}
            pricingReport={pricingReport}
            scorePrediction={scorePrediction}
            responseMatrix={responseMatrix}
            busy={actionBusy}
            disabled={!projectId}
            onBuildPricing={handleBuildPricingStrategy}
            onBuildScore={handleBuildScorePrediction}
            onBuildMatrix={handleBuildResponseMatrix}
            onSelectLine={setActiveLine}
          />
        </div>
      </div>

      <CorrectionModal
        open={modalOpen}
        busy={actionBusy}
        onClose={() => setModalOpen(false)}
        onSubmit={handleCorrectionSubmit}
      />
      {humanActionPrompt ? (
        <HumanActionPrompt
          open={humanPromptOpen}
          title={humanActionPrompt.title}
          message={humanActionPrompt.message}
          busy={actionBusy}
          actions={humanActionPrompt.actions}
          onClose={() => setHumanPromptOpen(false)}
        />
      ) : null}
    </main>
  );
}

function DeliveryVolumePanel({
  volumes,
  activeVolume,
  onActiveVolumeChange
}: {
  volumes: Record<DeliveryVolumeKey, DeliveryVolumePreview> | null;
  activeVolume: DeliveryVolumeKey;
  onActiveVolumeChange: (volume: DeliveryVolumeKey) => void;
}) {
  const active = volumes?.[activeVolume] ?? null;

  return (
    <section className="flex max-h-[640px] flex-col rounded-lg border border-line bg-panel shadow-panel">
      <div className="flex h-12 items-center justify-between border-b border-line px-4">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-brand" />
          <h2 className="text-sm font-semibold text-ink">分卷文件</h2>
        </div>
        {active ? (
          <span className="text-xs text-muted">{active.char_count} 字</span>
        ) : null}
      </div>

      <div className="border-b border-line p-3">
        <div className="grid grid-cols-3 gap-2">
          {deliveryVolumes.map((volume) => {
            const item = volumes?.[volume.key] ?? null;
            return (
              <button
                key={volume.key}
                type="button"
                onClick={() => onActiveVolumeChange(volume.key)}
                className={[
                  "rounded-md border px-2 py-2 text-left transition",
                  activeVolume === volume.key
                    ? "border-brand bg-blue-50 text-brand"
                    : "border-line bg-white text-ink hover:border-brand"
                ].join(" ")}
              >
                <span className="block text-xs font-semibold">{volume.label}</span>
                <span className="mt-1 block text-[11px] text-muted">
                  {item ? `${item.line_count} 行` : "待生成"}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-[280px] flex-1 overflow-auto bg-field px-4 py-3">
        {active ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-ink">
            {active.markdown}
          </pre>
        ) : (
          <div className="grid h-full min-h-64 place-items-center rounded-md border border-dashed border-line bg-white text-sm text-muted">
            等待生成后预览分卷内容
          </div>
        )}
      </div>
    </section>
  );
}

function buildHumanActionPrompt(
  status: string,
  context: {
    canStartWorkflow: boolean;
    canConfirm: boolean;
    actionBusy: boolean;
    onClose: () => void;
    onStartWorkflow: () => void;
    onOpenCorrection: () => void;
    onApprove: () => void;
  }
) {
  if (status === "parsed") {
    return {
      title: "需要确认解析结果",
      message: "招标文件已经解析完成。请检查项目名称、资质要求、评分项和废标条款，确认后再进入大纲生成。",
      actions: [
        {
          label: "去确认",
          tone: "primary" as const,
          icon: "check" as const,
          onClick: context.onClose
        }
      ]
    };
  }

  if (status === "outline_ready") {
    return {
      title: "需要确认生成大纲",
      message: "默认标书大纲已经生成。请检查章节顺序和每章重点，确认后系统才会进入 RAG 检索和正文生成。",
      actions: [
        {
          label: "去确认",
          tone: "primary" as const,
          icon: "check" as const,
          onClick: context.onClose
        }
      ]
    };
  }

  if (status === "outline_review") {
    return {
      title: "等待人工确认大纲",
      message: "工作流已暂停在生成前确认节点。请先保存确认版解析结果和大纲，再开始生成标书。",
      actions: [
        {
          label: "开始生成",
          tone: "primary" as const,
          icon: "play" as const,
          disabled: !context.canStartWorkflow || context.actionBusy,
          onClick: context.onStartWorkflow
        }
      ]
    };
  }

  if (status === "human_review") {
    return {
      title: "需要人工终审",
      message: "审查和修正循环已完成，系统正在等待你批准继续导出，或提交人工修正意见。",
      actions: [
        {
          label: "手动修改",
          tone: "neutral" as const,
          icon: "edit" as const,
          disabled: !context.canConfirm,
          onClick: context.onOpenCorrection
        },
        {
          label: "批准并继续",
          tone: "success" as const,
          icon: "check" as const,
          disabled: !context.canConfirm,
          onClick: context.onApprove
        }
      ]
    };
  }

  if (status === "needs_revision") {
    return {
      title: "需要人工修正",
      message: "当前项目已退回修正。请打开修正窗口补充意见，或编辑正文后重新保存审查。",
      actions: [
        {
          label: "打开修改",
          tone: "primary" as const,
          icon: "edit" as const,
          onClick: context.onOpenCorrection
        }
      ]
    };
  }

  return null;
}
