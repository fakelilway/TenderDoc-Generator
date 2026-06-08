"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Download,
  FileStack,
  FolderOpen,
  Loader2,
  LogOut,
  PencilLine,
  RefreshCw,
  TriangleAlert
} from "lucide-react";
import { AdminUsersPanel } from "@/components/AdminUsersPanel";
import { CorrectionModal } from "@/components/CorrectionModal";
import { DraftEditor } from "@/components/DraftEditor";
import { FinalChecklistPanel } from "@/components/FinalChecklistPanel";
import { HumanActionPrompt } from "@/components/HumanActionPrompt";
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { MarkdownPreview } from "@/components/MarkdownPreview";
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
  BidOutlineSection,
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

const finalStatuses = new Set([
  "approved",
  "finished",
  "generated",
  "failed",
  "generation_failed"
]);

const runningStatuses = new Set([
  "uploading",
  "parsing",
  "processing",
  "generating",
  "reviewing",
  "needs_revision",
  "outline_review"
]);

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
    needs_revision: "待修正",
    approved: "已批准",
    finished: "已完成",
    failed: "失败",
    generation_failed: "生成失败"
  };
  return labels[status] ?? status;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
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
  const [ragQuery, setRagQuery] = useState("施工组织设计 技术标 模板");
  const [ragDocumentType, setRagDocumentType] = useState("");
  const [ragSpecialty, setRagSpecialty] = useState("");
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
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
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

  const canConfirm = Boolean(projectId && workflowState?.awaiting_human);
  const canStartWorkflow = Boolean(
    projectId && ["outline_confirmed", "outline_review"].includes(status)
  );
  const canDownload = Boolean(
    projectId && ["approved", "finished", "generated"].includes(status)
  );
  const statusText = useMemo(() => readableStatus(status), [status]);
  const statusBusy = busy || actionBusy || runningStatuses.has(status);
  const applyWorkflowSnapshot = useCallback(
    (state?: WorkflowState | null, report?: ReviewReport | null) => {
      if (state) {
        setWorkflowState(state);
        if (state.status) {
          setStatus(state.status);
        }
        if (state.draft_markdown) {
          setMarkdown(state.draft_markdown);
        }
        if (state.parsed) {
          setParsedJson(state.parsed);
          setParsedJsonText(JSON.stringify(state.parsed, null, 2));
        }
        if (state.bid_outline) {
          setOutline(state.bid_outline);
        }
        if (state.selected_chunk_ids) {
          setSelectedChunkIds(state.selected_chunk_ids);
        }
        if (state.rag_references) {
          setRagReferences(state.rag_references);
        }
        if (state.final_checklist) {
          setFinalChecklist(state.final_checklist);
          if (state.final_checklist.response_matrix) {
            setResponseMatrix(state.final_checklist.response_matrix);
          }
        }
        if (state.final_versions) {
          setFinalVersions(state.final_versions);
        }
        if (state.review_report) {
          setReviewReport(state.review_report);
        }
        if (state.pricing_strategy) {
          setPricingStrategy(state.pricing_strategy as PricingStrategy);
        }
      }
      if (report) {
        setReviewReport(report);
      }
    },
    []
  );

  const refreshProject = useCallback(
    async (id: number, silent = false) => {
      try {
        const projectStatus = await getProjectStatus(id);
        setStatus(projectStatus.status);
        if (projectStatus.parsed) {
          const result = await getProjectResult(id);
          if (result.parsed_json) {
            setParsedJson(result.parsed_json);
            setParsedJsonText(JSON.stringify(result.parsed_json, null, 2));
          }
        }

        const reviewSnapshot = await getProjectReviewReport(id);
        setStatus(reviewSnapshot.workflow_state?.status || reviewSnapshot.status);
        applyWorkflowSnapshot(
          reviewSnapshot.workflow_state,
          reviewSnapshot.review_report
        );
      } catch (refreshError) {
        if (!silent) {
          setError(errorMessage(refreshError));
        }
      }
    },
    [applyWorkflowSnapshot]
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
      } catch (workflowError) {
        autoStartedWorkflowProject.current = null;
        setStatus("failed");
        setError(errorMessage(workflowError));
      } finally {
        setActionBusy(false);
      }
    },
    [refreshProject]
  );

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
    [actionBusy, canConfirm, canStartWorkflow, projectId, status, startWorkflow]
  );

  useEffect(() => {
    if (initialProjectId) {
      void refreshProject(initialProjectId);
    }
  }, [initialProjectId, refreshProject]);

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
      "awaiting_human",
      "reviewing",
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
      setHumanPromptOpen(false);
      lastHumanPromptKey.current = "";
    setDownloadUrl(null);
    setActiveLine(null);

    try {
      setStatus("uploading");
      const created = await createProject(
        projectName.trim(),
        file,
        selectedTemplateId
      );
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
      setStatus(confirmed.status);
      setParsedJson(confirmed.confirmed_parsed_json);
      setParsedJsonText(JSON.stringify(confirmed.confirmed_parsed_json, null, 2));
      const built = await buildProjectOutline(projectId);
      setStatus(built.status);
      setOutline(built.bid_outline);
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
      setStatus(built.status);
      setOutline(built.bid_outline);
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
      setStatus(saved.status);
      setOutline(saved.bid_outline);
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
        documentType: ragDocumentType.trim() || undefined,
        specialty: ragSpecialty.trim() || undefined,
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
      setStatus(saved.status);
      setMarkdown(saved.draft_markdown);
      if (saved.review_report) {
        setReviewReport(saved.review_report);
      }
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

  async function handleApprove() {
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
    } catch (approveError) {
      setError(errorMessage(approveError));
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
    artifact: "docx" | "markdown" | "review" = "docx"
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
      if (artifact === "docx") {
        setDownloadUrl(result.download_url);
      }
      window.open(result.download_url, "_blank", "noopener,noreferrer");
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
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
        <div className="flex min-h-16 flex-col gap-3 px-4 py-3 lg:flex-row lg:items-center lg:justify-between lg:px-6">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-ink">TenderDoc Generator</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
              <span>Project {projectId ?? "-"}</span>
              <span className="rounded-md border border-line bg-field px-2 py-1 font-medium text-ink">
                {statusText}
              </span>
              {downloadUrl ? (
                <a
                  href={downloadUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-brand hover:underline"
                >
                  DOCX
                </a>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {username ? (
              <span className="inline-flex h-9 items-center rounded-md border border-line bg-field px-3 text-sm font-medium text-muted">
                {username}
              </span>
            ) : null}
            <a
              href="/projects"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
            >
              <FolderOpen className="h-4 w-4" />
              历史项目
            </a>
            {isAdmin ? (
              <a
                href="/templates"
                className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
              >
                <FileStack className="h-4 w-4" />
                模板库
              </a>
            ) : null}
            <button
              type="button"
              disabled={!projectId || actionBusy}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field disabled:cursor-not-allowed disabled:text-muted"
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
              className="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
              onClick={() => projectId && startWorkflow(projectId)}
            >
              <Loader2 className={actionBusy ? "h-4 w-4 animate-spin" : "hidden"} />
              开始生成
            </button>
            <button
              type="button"
              disabled={!canConfirm || actionBusy}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field disabled:cursor-not-allowed disabled:text-muted"
              onClick={() => setModalOpen(true)}
            >
              <PencilLine className="h-4 w-4" />
              手动修改
            </button>
            <button
              type="button"
              disabled={!canConfirm || actionBusy}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-ok px-3 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-green-300"
              onClick={handleApprove}
            >
              <CheckCircle2 className="h-4 w-4" />
              批准并继续
            </button>
            <button
              type="button"
              disabled={!canDownload || actionBusy}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
              onClick={() => handleDownload("docx")}
            >
              <Download className="h-4 w-4" />
              下载标书
            </button>
            <button
              type="button"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
              onClick={handleLogout}
            >
              <LogOut className="h-4 w-4" />
              退出
            </button>
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
        <div className="mx-4 mt-4 flex flex-col gap-3 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-ok lg:mx-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="font-semibold">标书已完成，可下载</p>
              <p className="text-xs text-green-700">
                可分别下载最终 DOCX、Markdown 源文件与审查报告；下载链接过期后再次点击即可重新获取。
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => handleDownload("docx")}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-ok px-3 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-green-300"
            >
              <Download className="h-4 w-4" />
              DOCX
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
          <StatusRail
            status={status}
            busy={statusBusy}
            traceEvents={workflowState?.trace_events}
          />
          <KnowledgePanel />
          <RagSelectionPanel
            query={ragQuery}
            documentType={ragDocumentType}
            specialty={ragSpecialty}
            tagText={ragTagText}
            results={ragResults}
            selectedIds={selectedChunkIds}
            references={ragReferences}
            busy={actionBusy}
            onQueryChange={setRagQuery}
            onDocumentTypeChange={setRagDocumentType}
            onSpecialtyChange={setRagSpecialty}
            onTagTextChange={setRagTagText}
            onSearch={handleSearchKnowledge}
            onToggle={handleToggleChunk}
            onSave={handleSaveKnowledgeSelection}
          />
          <AdminUsersPanel />
        </div>

        <div className="space-y-4">
          <ParsedReviewPanel
            parsed={parsedJson}
            value={parsedJsonText}
            busy={actionBusy}
            onChange={setParsedJsonText}
            onSave={handleConfirmParsed}
          />
          <OutlineEditor
            outline={outline}
            busy={actionBusy}
            onChange={setOutline}
            onBuild={handleBuildOutline}
            onSave={handleSaveOutline}
          />
          <DraftEditor
            markdown={markdown}
            busy={actionBusy}
            onChange={setMarkdown}
            onSave={handleSaveDraft}
            onChecklist={handleFinalChecklist}
          />
          <MarkdownPreview markdown={markdown} activeLine={activeLine} />
        </div>

        <div className="space-y-4">
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
