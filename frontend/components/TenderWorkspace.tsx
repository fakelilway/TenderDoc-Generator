"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  CheckCircle2,
  Download,
  FileText,
  FileStack,
  Building2,
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
import { ParsedReviewPanel } from "@/components/ParsedReviewPanel";
import { RagSelectionPanel } from "@/components/RagSelectionPanel";
import { RiskPanel } from "@/components/RiskPanel";
import { StatusRail, StatusProgressOverlay } from "@/components/StatusRail";
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
  listKnowledgeDocuments,
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
    outline_ready: "可以生成",
    outline_review: "可以生成",
    outline_confirmed: "可以生成",
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
    parsed_confirmed: "下一步：点击「开始生成」，系统会调用大模型生成完整标书。",
    processing: "正在准备生成上下文，系统会读取招标文件、知识库和可选风格案例。",
    generating: "正在调用大模型生成标书。长文档会停留较久，请看实时状态。",
    reviewing: "正在审查废标风险和响应完整性。",
    human_review: "下一步：人工检查正文，必要时修改，然后批准并导出。",
    needs_revision: "下一步：根据审查意见修改正文，再重新确认。",
    approved: "标书已确认，可以下载 DOCX、PDF 或审查报告。",
    finished: "标书已完成，可以下载并进入新点制作软件封装。",
    generated: "标书已生成，可以预览、编辑并下载。",
    failed: "任务失败，请查看实时状态中的失败原因；修正配置或输入后可重新生成。",
    generation_failed: "生成失败，请检查模型 API、网络或提示词后重新生成。"
  };
  return copy[status] ?? "按左侧流程从上到下完成上传、解析、选资料、生成、审查和下载。";
}

function errorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function latestFailedTraceMessage(state?: WorkflowState | null) {
  const failed = [...(state?.trace_events ?? [])]
    .reverse()
    .find((event) => event.status === "failed" && event.message);
  return failed?.message;
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
  const [persistentError, setPersistentError] = useState<string | null>(null);
  const [reviewReport, setReviewReport] = useState<ReviewReport | null>(null);
  const [workflowState, setWorkflowState] = useState<WorkflowState | null>(null);
  const [parsedJson, setParsedJson] = useState<TenderRequirements | null>(null);
  const [parsedJsonText, setParsedJsonText] = useState("");
  const [outline, setOutline] = useState<BidOutlineSection[]>([]);
  const [documentOutline, setDocumentOutline] = useState<BidDocumentOutlineSection[]>(
    []
  );
  const [ragQuery, setRagQuery] = useState("施工组织设计 技术标 正奇案例");
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
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>("split");
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
  const chunkSaveSeq = useRef(0);
  const [knowledgeTags, setKnowledgeTags] = useState<string[]>([]);
  const [centerTab, setCenterTab] = useState<"parsed" | "draft" | "preview">("parsed");
  const [overlayDismissed, setOverlayDismissed] = useState(false);

  const reportError = useCallback((caught: unknown) => {
    const message = errorMessage(caught);
    setError(message);
    setPersistentError(message);
  }, []);

  const visibleError = persistentError ?? error;

  useEffect(() => {
    let cancelled = false;
    listKnowledgeDocuments()
      .then((response) => {
        if (cancelled) {
          return;
        }
        const tags = new Set<string>();
        for (const document of response.documents) {
          for (const tag of document.tags ?? []) {
            tags.add(tag);
          }
        }
        setKnowledgeTags(Array.from(tags).sort());
      })
      .catch(() => {
        // 标签 chips 只是辅助输入，知识库不可用时静默降级为手动输入
      });
    return () => {
      cancelled = true;
    };
  }, []);
  // Guards against stale/out-of-order refresh responses after project switches.
  const projectIdRef = useRef<number | null>(initialProjectId);
  const refreshSeq = useRef(0);
  // Last status applied by refreshProject, for detecting preview transitions.
  const lastRefreshedStatus = useRef<string | null>(null);

  const canConfirm = Boolean(
    projectId &&
      workflowState?.awaiting_human &&
      ["human_review", "needs_revision"].includes(status)
  );
  const canStartWorkflow = Boolean(
    projectId &&
      ["parsed_confirmed", "outline_ready", "outline_review", "outline_confirmed", "failed", "generation_failed"].includes(
        status
      )
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
  const progressOverlayOpen = !overlayDismissed && Boolean(
    busy ||
      runningStatuses.has(status) ||
      ["processing", "generating", "reviewing"].includes(status)
  );
  // Reset overlay dismissed flag when status changes
  useEffect(() => {
    setOverlayDismissed(false);
    // Auto-switch center tab based on workflow status
    if (status === "parsed" || status === "parsed_confirmed") {
      setCenterTab("parsed");
    } else if (
      ["generated", "reviewing", "human_review", "needs_revision", "draft_saved", "approved", "finished"].includes(status)
    ) {
      setCenterTab("preview");
    }
  }, [status]);
  const clearWorkflowDerivedState = useCallback(() => {
    setWorkflowState(null);
    setReviewReport(null);
    setFinalChecklist(null);
    setFinalVersions([]);
    setPricingStrategy(null);
    setPricingReport(null);
    setScorePrediction(null);
    setResponseMatrix(null);
    if (!dirtyFields.current.has("markdown")) {
      setMarkdown("");
      setDeliveryPreview(null);
    }
    setSelectedChunkIds([]);
    setRagReferences([]);
  }, []);

  const clearParsedDerivedState = useCallback(() => {
    if (!dirtyFields.current.has("parsed")) {
      setParsedJson(null);
      setParsedJsonText("");
    }
    // Outline is built/saved independently of parse; only clear on explicit project reset.
    // The polling loop in refreshProject can fire with parsed:false transiently,
    // and without bid_outline in workflow_state_json, cleared outline is unrecoverable.
  }, []);

  const applyWorkflowSnapshot = useCallback(
    (state?: WorkflowState | null, report?: ReviewReport | null) => {
      if (state) {
        setStateIfChanged(setWorkflowState, state);
        if (state.status) {
          setStatus(state.status);
        }
        // Surface failed trace message as persistent error so user can see
        // why generation failed on page reload.
        if (["failed", "generation_failed"].includes(state.status)) {
          const msg = latestFailedTraceMessage(state);
          if (msg) {
            setPersistentError(msg);
          }
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
      } else {
        clearWorkflowDerivedState();
      }
      if (report) {
        setStateIfChanged(setReviewReport, report);
      } else if (!state?.review_report) {
        setReviewReport(null);
      }
    },
    [clearWorkflowDerivedState]
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
        // Only clear parsed state when truly pre-parse, not on transient inconsistencies.
        // Outline is built independently and must survive polling.
        if (
          !projectStatus.parsed &&
          ["idle", "uploaded", "uploading"].includes(projectStatus.status)
        ) {
          clearParsedDerivedState();
        }
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
          reportError(refreshError);
        }
      }
    },
    [applyWorkflowSnapshot, clearParsedDerivedState, refreshDeliveryPreview, reportError]
  );

  const waitForParsedResult = useCallback(
    async (id: number) => {
      for (let attempt = 0; attempt < 180; attempt += 1) {
        const projectStatus = await getProjectStatus(id);
        if (projectIdRef.current !== id) {
          return null;
        }
        setStatus(projectStatus.status);
        if (projectStatus.parsed) {
          const result = await getProjectResult(id);
          if (projectIdRef.current !== id) {
            return null;
          }
          return result;
        }
        if (["failed", "generation_failed"].includes(projectStatus.status)) {
          const snapshot = await getProjectReviewReport(id).catch(() => null);
          const message =
            latestFailedTraceMessage(snapshot?.workflow_state) ||
            "解析失败：后端未能完成招标文件结构化解析。";
          throw new Error(message);
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      throw new Error("解析仍在进行中，请稍后刷新查看结果。");
    },
    []
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
        reportError(workflowError);
      } finally {
        setActionBusy(false);
      }
    },
    [refreshDeliveryPreview, refreshProject, reportError]
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
      reportError(approveError);
    } finally {
      setActionBusy(false);
    }
  }, [projectId, refreshDeliveryPreview, refreshProject, reportError]);

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
    if (!projectId || busy || actionBusy || finalStatuses.has(status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshProject(projectId, true);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [actionBusy, busy, projectId, refreshProject, status]);

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
    setPersistentError(null);
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
      await parseProject(created.project_id);
      const parsed = await waitForParsedResult(created.project_id);
      if (!parsed) {
        return;
      }
      if (parsed.parsed_json) {
        setStatus(parsed.status);
        setParsedJson(parsed.parsed_json);
        setParsedJsonText(JSON.stringify(parsed.parsed_json, null, 2));
      }
    } catch (runError) {
      setStatus("failed");
      reportError(runError);
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmParsed() {
    if (!projectId) {
      return;
    }
    refreshSeq.current += 1;
    setActionBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(parsedJsonText) as Record<string, unknown>;
      const confirmed = await confirmParsedProject(projectId, parsed);
      dirtyFields.current.delete("parsed");
      setStatus(confirmed.status);
      setParsedJson(confirmed.confirmed_parsed_json);
      setParsedJsonText(JSON.stringify(confirmed.confirmed_parsed_json, null, 2));
      // Build outline, then auto-confirm it (outline editor UI removed in v2)
      const built = await buildProjectOutline(projectId);
      dirtyFields.current.delete("outline");
      setOutline(built.bid_outline);
      setDocumentOutline(built.document_outline ?? []);
      // Auto-confirm outline so user can start generation immediately
      const saved = await saveProjectOutline(
        projectId,
        built.bid_outline,
        built.document_outline
      );
      setStatus(saved.status);
    } catch (confirmError) {
      reportError(confirmError);
    } finally {
      setActionBusy(false);
    }
  }

  async function handleBuildOutline() {
    if (!projectId) {
      return;
    }
    refreshSeq.current += 1;
    setActionBusy(true);
    setError(null);
    try {
      const built = await buildProjectOutline(projectId);
      dirtyFields.current.delete("outline");
      setStatus(built.status);
      setOutline(built.bid_outline);
      setDocumentOutline(built.document_outline ?? []);
    } catch (outlineError) {
      reportError(outlineError);
    } finally {
      setActionBusy(false);
    }
  }

  async function handleSaveOutline() {
    if (!projectId) {
      return;
    }
    refreshSeq.current += 1;
    setActionBusy(true);
    setError(null);
    try {
      const saved = await saveProjectOutline(projectId, outline, documentOutline);
      dirtyFields.current.delete("outline");
      setStatus(saved.status);
      setOutline(saved.bid_outline);
      setDocumentOutline(saved.document_outline ?? []);
    } catch (outlineError) {
      reportError(outlineError);
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
      reportError(searchError);
    } finally {
      setActionBusy(false);
    }
  }

  async function handleToggleChunk(chunkId: number) {
    const next = selectedChunkIds.includes(chunkId)
      ? selectedChunkIds.filter((id) => id !== chunkId)
      : [...selectedChunkIds, chunkId];
    setSelectedChunkIds(next);
    if (!projectId) {
      dirtyFields.current.add("chunks");
      return;
    }
    // 勾选即采用：立即持久化，序号防止快速连点时旧响应覆盖新状态
    const seq = ++chunkSaveSeq.current;
    setError(null);
    try {
      const saved = await saveKnowledgeSelection(projectId, next);
      if (seq === chunkSaveSeq.current) {
        dirtyFields.current.delete("chunks");
        setSelectedChunkIds(saved.selected_chunk_ids);
        setRagReferences(saved.references);
      }
    } catch (saveError) {
      reportError(saveError);
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
      reportError(saveError);
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
      reportError(checklistError);
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
      reportError(strategyError);
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
      reportError(scoreError);
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
      reportError(matrixError);
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
      reportError(correctionError);
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
      reportError(downloadError);
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
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,rgba(255,255,255,0.96),rgba(245,245,247,0)_34%),linear-gradient(180deg,#f9f9fb_0%,#f5f5f7_42%,#eef0f4_100%)] text-[#1d1d1f]">
      <header className="sticky top-0 z-20 border-b border-white/60 bg-white/54 backdrop-blur-2xl">
        <div className="mx-auto flex max-w-[1840px] flex-col gap-3 px-4 py-3 lg:px-6">
          <div className="ios-glass flex flex-col gap-3 rounded-[28px] border px-3 py-3 sm:px-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-center gap-3.5">
              <AppLogo className="h-14 w-14 rounded-[18px] border border-white/80 bg-white/90 p-1 shadow-[0_10px_24px_rgba(15,23,42,0.12)]" />
              <div className="min-w-0">
                <div className="flex flex-wrap items-end gap-3">
                  <div
                    className="inline-block origin-bottom-left -rotate-2 -skew-x-6 bg-[linear-gradient(105deg,#082a55_0%,#082a55_46%,#b88a45_48%,#c99d5b_100%)] bg-clip-text text-[25px] font-black leading-none tracking-[0.16em] text-transparent"
                    style={{
                      fontFamily:
                        '"Songti SC", "STSong", "SimSun", "PingFang SC", serif'
                    }}
                  >
                    正奇建设
                  </div>
                  <span className="mb-0.5 truncate text-[13px] font-semibold text-[#3a3a3c]">
                    标书生成工作台
                  </span>
                  <span className="rounded-full bg-black/[0.06] px-2.5 py-1 text-xs font-medium text-[#636366]">
                    Project {projectId ?? "-"}
                  </span>
                </div>
                <p className="mt-0.5 line-clamp-1 text-[13px] leading-5 text-[#6e6e73]">
                  {nextStepText}
                </p>
              </div>
            </div>

            <nav className="flex items-center gap-2 overflow-x-auto pb-1 lg:justify-end lg:pb-0">
              <NavLinkButton href="/projects" icon={FolderOpen}>
                历史项目
              </NavLinkButton>
              <NavLinkButton href="/knowledge" icon={Database}>
                知识库
              </NavLinkButton>
              <NavLinkButton href="/company" icon={Building2}>
                公司档案
              </NavLinkButton>
              {isAdmin ? (
                <>
                  <NavLinkButton href="/templates" icon={FileStack}>
                    风格库
                  </NavLinkButton>
                  <NavLinkButton href="/admin/users" icon={Users}>
                    账号管理
                  </NavLinkButton>
                </>
              ) : null}
              {username ? (
                <span className="inline-flex h-10 shrink-0 items-center rounded-full border border-white/70 bg-white/56 px-3.5 text-sm font-medium text-[#6e6e73]">
                  {username}
                </span>
              ) : null}
              <button
                type="button"
                className="inline-flex h-10 shrink-0 items-center gap-2 rounded-full border border-white/70 bg-white/56 px-3.5 text-sm font-medium text-[#1d1d1f] transition hover:bg-white/86"
                onClick={handleLogout}
              >
                <LogOut className="h-4 w-4" />
                退出
              </button>
            </nav>
          </div>

          <div className="flex flex-col gap-3 rounded-[24px] border border-white/70 bg-white/58 px-3 py-3 shadow-[0_12px_34px_rgba(15,23,42,0.055)] backdrop-blur-xl lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <span
                className={[
                  "h-2.5 w-2.5 shrink-0 rounded-full",
                  ["failed", "generation_failed"].includes(status)
                    ? "bg-[#ff3b30]"
                    : statusBusy
                      ? "bg-[#ff9f0a]"
                      : canDownload
                        ? "bg-[#34c759]"
                        : "bg-[#007aff]"
                ].join(" ")}
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[#1d1d1f]">
                  {statusText}
                </p>
                <p className="truncate text-xs text-[#6e6e73]">
                  {statusBusy ? "任务正在运行，请保持页面打开" : "当前等待人工操作"}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 overflow-x-auto pb-1 lg:justify-end lg:pb-0">
              <button
                type="button"
                disabled={!projectId || actionBusy}
                className="inline-flex h-10 shrink-0 items-center gap-2 rounded-full border border-white/70 bg-white/70 px-3.5 text-sm font-medium text-[#1d1d1f] transition hover:bg-white disabled:cursor-not-allowed disabled:text-[#a1a1a6]"
                onClick={handleRefresh}
              >
                {actionBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                刷新
              </button>
              <button
                type="button"
                disabled={!canStartWorkflow || actionBusy}
                className="inline-flex h-10 shrink-0 items-center gap-2 rounded-full bg-[#1d1d1f] px-4 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(29,29,31,0.18)] transition hover:bg-black disabled:cursor-not-allowed disabled:bg-[#d1d1d6] disabled:shadow-none"
                onClick={() => projectId && startWorkflow(projectId)}
              >
                <Loader2 className={actionBusy ? "h-4 w-4 animate-spin" : "hidden"} />
                {["failed", "generation_failed"].includes(status) ? "重新生成" : "开始生成"}
              </button>
              {canConfirm ? (
                <>
                  <button
                    type="button"
                    disabled={actionBusy}
                    className="inline-flex h-10 shrink-0 items-center gap-2 rounded-full border border-white/70 bg-white/70 px-3.5 text-sm font-medium text-[#1d1d1f] transition hover:bg-white disabled:cursor-not-allowed disabled:text-[#a1a1a6]"
                    onClick={() => setModalOpen(true)}
                  >
                    <PencilLine className="h-4 w-4" />
                    修改意见
                  </button>
                  <button
                    type="button"
                    disabled={actionBusy}
                    className="inline-flex h-10 shrink-0 items-center gap-2 rounded-full bg-[#34c759] px-4 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(52,199,89,0.22)] transition hover:bg-[#2fb34f] disabled:cursor-not-allowed disabled:bg-[#b8e8c3] disabled:shadow-none"
                    onClick={handleApprove}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    确认导出
                  </button>
                </>
              ) : null}
            </div>
          </div>
        </div>
      </header>

      {visibleError ? (
        <div className="mx-auto mt-4 flex max-w-[1840px] items-start gap-3 rounded-[22px] border border-[#ff9f0a]/20 bg-[#fff4df]/85 px-4 py-3 text-sm text-[#b45309] shadow-[0_12px_30px_rgba(180,83,9,0.08)] backdrop-blur lg:px-5">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <p className="flex-1 whitespace-pre-wrap">{visibleError}</p>
          <button
            type="button"
            className="rounded-full border border-[#ff9f0a]/20 bg-white/70 px-3 py-1 text-xs font-semibold text-[#b45309] hover:bg-white"
            onClick={() => {
              setPersistentError(null);
              setError(null);
            }}
          >
            关闭
          </button>
        </div>
      ) : null}

      {canDownload ? (
        <div className="ios-panel mx-auto mt-4 flex max-w-[1840px] flex-col gap-4 rounded-[26px] border px-4 py-4 text-sm text-[#1d1d1f] lg:px-5">
          <div className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[#34c759]" />
            <div>
              <p className="font-semibold">标书已完成，可按投递网站要求下载</p>
              <p className="text-xs text-[#6e6e73]">
                商务文件、技术文件、报价文件分别下载投递。
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-full border border-black/[0.06] bg-black/[0.045] p-1">
                {(["docx", "pdf"] as DeliveryFormat[]).map((format) => (
                  <button
                    key={format}
                    type="button"
                    onClick={() => setDeliveryFormat(format)}
                    className={[
                      "h-8 rounded-full px-3 text-xs font-semibold uppercase transition",
                      deliveryFormat === format
                        ? "bg-white text-[#1d1d1f] shadow-sm"
                        : "text-[#6e6e73] hover:bg-white/60"
                    ].join(" ")}
                  >
                    {format}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {deliveryVolumes.map((volume) => (
                <button
                  key={volume.key}
                  type="button"
                  disabled={actionBusy}
                  onClick={() =>
                    handleDownload(
                      deliveryArtifact("split", deliveryFormat, volume.key)
                    )
                  }
                  className="inline-flex h-10 items-center gap-2 rounded-full bg-[#34c759] px-4 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(52,199,89,0.18)] hover:bg-[#2fb34f] disabled:cursor-not-allowed disabled:bg-[#b8e8c3]"
                >
                  <Download className="h-4 w-4" />
                  {volume.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-black/[0.06] pt-3">
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => handleDownload("docx")}
              className="inline-flex h-9 items-center gap-2 rounded-full border border-black/[0.06] bg-white/70 px-3.5 text-sm font-medium text-[#1d1d1f] hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              原始DOCX
            </button>
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => handleDownload("review")}
              className="inline-flex h-9 items-center gap-2 rounded-full border border-black/[0.06] bg-white/70 px-3.5 text-sm font-medium text-[#1d1d1f] hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              审查报告
            </button>
          </div>
        </div>
      ) : null}

      <div className="mx-auto grid max-w-[1840px] gap-4 p-4 lg:grid-cols-[340px_minmax(0,1fr)_360px] lg:p-6">
        {/* Left column: Upload + Status + RAG */}
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
          {projectId ? (
            <StatusRail
              status={status}
              busy={statusBusy}
              traceEvents={workflowState?.trace_events ?? []}
            />
          ) : null}
          {projectId ? (
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
              availableTags={knowledgeTags}
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
            />
          ) : null}
        </div>

        {/* Center column: Tab-based layout for parsed / draft / preview */}
        <div className="space-y-0">
          <div className="ios-panel rounded-[26px] border">
            {/* Tab bar */}
            <div className="flex h-12 items-center gap-1 border-b border-black/[0.06] px-3">
              <TabButton
                active={centerTab === "parsed"}
                label="解析确认"
                badge={parsedJson ? "ok" : undefined}
                onClick={() => setCenterTab("parsed")}
              />
              <TabButton
                active={centerTab === "draft"}
                label="正文编辑"
                badge={markdown.trim() ? "ok" : undefined}
                onClick={() => setCenterTab("draft")}
              />
              <TabButton
                active={centerTab === "preview"}
                label="标书预览"
                badge={markdown.trim() ? "ok" : undefined}
                onClick={() => setCenterTab("preview")}
              />
            </div>
            {/* Tab content */}
            <div className="p-4">
              {centerTab === "parsed" ? (
                <ParsedReviewPanel
                  parsed={parsedJson}
                  value={parsedJsonText}
                  busy={actionBusy}
                  onChange={handleParsedJsonTextChange}
                  onSave={handleConfirmParsed}
                />
              ) : null}
              {centerTab === "draft" ? (
                <DraftEditor
                  markdown={markdown}
                  busy={actionBusy}
                  onChange={handleMarkdownChange}
                  onSave={handleSaveDraft}
                  onChecklist={handleFinalChecklist}
                />
              ) : null}
              {centerTab === "preview" ? (
                <MarkdownPreview markdown={markdown} activeLine={activeLine} />
              ) : null}
            </div>
          </div>
        </div>

        {/* Right column: Progressive disclosure */}
        <div className="space-y-4">
          {deliveryPreview ? (
            <DeliveryVolumePanel
              volumes={deliveryPreview}
              activeVolume={activeDeliveryVolume}
              onActiveVolumeChange={setActiveDeliveryVolume}
            />
          ) : null}
          {reviewReport ? (
            <RiskPanel
              report={reviewReport}
              activeLine={activeLine}
              onSelect={(line) => { setActiveLine(line); if (line != null) setCenterTab("preview"); }}
            />
          ) : null}
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
            onSelectLine={(line) => { setActiveLine(line); if (line != null) setCenterTab("preview"); }}
          />
          {!deliveryPreview && !reviewReport && !finalChecklist && !projectId ? (
            <div className="ios-panel grid min-h-[200px] place-items-center rounded-[26px] border p-6 text-center">
              <div>
                <p className="text-sm font-medium text-[#1d1d1f]">右侧面板</p>
                <p className="mt-1 text-xs text-[#6e6e73]">上传招标文件后，分卷预览、审查报告和评分分析将在这里显示</p>
              </div>
            </div>
          ) : null}
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
      <StatusProgressOverlay
        open={progressOverlayOpen}
        status={status}
        busy={statusBusy}
        traceEvents={workflowState?.trace_events}
        onDismiss={() => setOverlayDismissed(true)}
      />
    </main>
  );
}

function TabButton({
  active,
  label,
  badge,
  onClick
}: {
  active: boolean;
  label: string;
  badge?: "ok" | "warn";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "relative inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-xs font-semibold transition",
        active
          ? "bg-[#007aff]/10 text-[#007aff]"
          : "text-[#6e6e73] hover:bg-black/[0.04] hover:text-[#1d1d1f]"
      ].join(" ")}
    >
      {label}
      {badge === "ok" ? (
        <span className="h-1.5 w-1.5 rounded-full bg-[#34c759]" />
      ) : null}
    </button>
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
    <section className="ios-panel flex max-h-[480px] flex-col rounded-[26px] border">
      <div className="flex h-14 items-center justify-between border-b border-black/[0.06] px-4">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-[#007aff]/10 text-[#007aff]">
            <FileText className="h-4 w-4" />
          </span>
          <h2 className="text-sm font-semibold text-[#1d1d1f]">分卷文件</h2>
        </div>
        {active ? (
          <span className="rounded-full bg-black/[0.05] px-2.5 py-1 text-xs text-[#6e6e73]">
            {active.char_count} 字
          </span>
        ) : null}
      </div>

      <div className="border-b border-black/[0.06] p-3">
        <div className="grid grid-cols-3 gap-2">
          {deliveryVolumes.map((volume) => {
            const item = volumes?.[volume.key] ?? null;
            return (
              <button
                key={volume.key}
                type="button"
                onClick={() => onActiveVolumeChange(volume.key)}
                className={[
                  "rounded-[18px] border px-3 py-2 text-left transition",
                  activeVolume === volume.key
                    ? "border-[#007aff]/20 bg-white text-[#007aff] shadow-sm"
                    : "border-black/[0.06] bg-white/48 text-[#1d1d1f] hover:bg-white"
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

      <div className="min-h-[280px] flex-1 overflow-auto bg-white/28 px-4 py-3">
        {active ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-ink">
            {active.markdown}
          </pre>
        ) : (
          <div className="grid h-full min-h-64 place-items-center rounded-[20px] border border-dashed border-black/[0.08] bg-white/54 text-sm text-[#8e8e93]">
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
      message: "招标文件已经解析完成。请检查项目名称、资质要求、评分项和废标条款，确认后即可开始生成。",
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
      title: "解析已确认，可以开始生成",
      message: "解析结果和大纲已就绪。点击「开始生成」，系统将检索知识库并生成标书正文。",
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

  if (["failed", "generation_failed"].includes(status)) {
    return {
      title: "任务失败，可重新生成",
      message:
        "请先查看实时状态中的失败原因。修正模型配置、招标文件解析结果或目录后，可以重新发起生成流程。",
      actions: [
        {
          label: "重新生成",
          tone: "primary" as const,
          icon: "play" as const,
          disabled: !context.canStartWorkflow || context.actionBusy,
          onClick: context.onStartWorkflow
        }
      ]
    };
  }

  return null;
}
