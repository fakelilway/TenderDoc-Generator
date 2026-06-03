"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Download,
  Loader2,
  PencilLine,
  RefreshCw,
  TriangleAlert
} from "lucide-react";
import { CorrectionModal } from "@/components/CorrectionModal";
import { MarkdownPreview } from "@/components/MarkdownPreview";
import { RiskPanel } from "@/components/RiskPanel";
import { StatusRail } from "@/components/StatusRail";
import { UploadPanel } from "@/components/UploadPanel";
import {
  confirmProject,
  createProject,
  getProjectDownload,
  getProjectReviewReport,
  getProjectStatus,
  parseProject,
  runProjectWorkflow
} from "@/lib/api";
import type { ReviewReport, WorkflowState } from "@/lib/types";

const finalStatuses = new Set([
  "approved",
  "finished",
  "generated",
  "failed",
  "generation_failed"
]);

function readableStatus(status: string) {
  const labels: Record<string, string> = {
    idle: "待上传",
    uploading: "上传中",
    uploaded: "已上传",
    parsing: "解析中",
    parsed: "已解析",
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
  const [markdown, setMarkdown] = useState("");
  const [activeLine, setActiveLine] = useState<number | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const canConfirm = Boolean(projectId && workflowState?.awaiting_human);
  const canDownload = Boolean(
    projectId && ["approved", "finished", "generated"].includes(status)
  );
  const statusText = useMemo(() => readableStatus(status), [status]);

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
        if (state.review_report) {
          setReviewReport(state.review_report);
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

  useEffect(() => {
    if (initialProjectId) {
      void refreshProject(initialProjectId);
    }
  }, [initialProjectId, refreshProject]);

  useEffect(() => {
    if (!projectId || finalStatuses.has(status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshProject(projectId, true);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [projectId, refreshProject, status]);

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
    setMarkdown("");
    setDownloadUrl(null);
    setActiveLine(null);

    try {
      setStatus("uploading");
      const created = await createProject(projectName.trim(), file);
      setProjectId(created.project_id);
      window.history.pushState(null, "", `/project/${created.project_id}`);
      setStatus(created.status);

      setStatus("parsing");
      const parsed = await parseProject(created.project_id);
      setStatus(parsed.status);

      setStatus("reviewing");
      const workflow = await runProjectWorkflow(created.project_id);
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

      await refreshProject(created.project_id);
    } catch (runError) {
      setStatus("failed");
      setError(errorMessage(runError));
    } finally {
      setBusy(false);
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

  async function handleDownload() {
    if (!projectId) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      const result = await getProjectDownload(projectId);
      setDownloadUrl(result.download_url);
      window.open(result.download_url, "_blank", "noopener,noreferrer");
    } catch (downloadError) {
      setError(errorMessage(downloadError));
    } finally {
      setActionBusy(false);
    }
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
              onClick={handleDownload}
            >
              <Download className="h-4 w-4" />
              下载标书
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

      <div className="grid gap-4 p-4 lg:grid-cols-[320px_minmax(0,1fr)_360px] lg:p-6">
        <div className="space-y-4">
          <UploadPanel
            projectName={projectName}
            file={file}
            busy={busy}
            onProjectNameChange={setProjectName}
            onFileChange={handleFileChange}
            onSubmit={handleCreateAndRun}
          />
          <StatusRail status={status} busy={busy || actionBusy} />
        </div>

        <MarkdownPreview markdown={markdown} activeLine={activeLine} />

        <RiskPanel
          report={reviewReport}
          activeLine={activeLine}
          onSelect={setActiveLine}
        />
      </div>

      <CorrectionModal
        open={modalOpen}
        busy={actionBusy}
        onClose={() => setModalOpen(false)}
        onSubmit={handleCorrectionSubmit}
      />
    </main>
  );
}
