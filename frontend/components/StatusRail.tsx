"use client";

import {
  CheckCircle2,
  Circle,
  Download,
  FileCheck2,
  FileText,
  Loader2,
  ShieldCheck,
  UploadCloud,
  UserCheck,
  X
} from "lucide-react";
import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import type { WorkflowTraceEvent } from "@/lib/types";

type Stage = {
  key: string;
  label: string;
  icon: LucideIcon;
  traceStages: string[];
  pendingText: string;
  activeText: string;
  doneText: string;
};

const stages: Stage[] = [
  {
    key: "upload",
    label: "上传",
    icon: UploadCloud,
    traceStages: ["upload"],
    pendingText: "等待选择招标文件",
    activeText: "上传原始文件到 MinIO",
    doneText: "原始招标文件已入库"
  },
  {
    key: "parse",
    label: "解析",
    icon: FileText,
    traceStages: ["parse", "parsing", "outline"],
    pendingText: "等待解析 Agent 提取结构化要求",
    activeText: "PDF/Word 文本抽取 + LLM 结构化解析",
    doneText: "资质、评分项、废标条款已保存"
  },
  {
    key: "generate",
    label: "生成",
    icon: FileCheck2,
    traceStages: ["generate", "rag"],
    pendingText: "等待 RAG 检索与生成 Agent",
    activeText: "构建大纲、检索知识库并生成 Markdown 初稿",
    doneText: "标书 Markdown 初稿已生成"
  },
  {
    key: "review",
    label: "审查",
    icon: ShieldCheck,
    traceStages: ["review", "correct"],
    pendingText: "等待规则引擎和 LLM 审查",
    activeText: "规则引擎 + LLM 检查废标风险",
    doneText: "审查报告已生成"
  },
  {
    key: "confirm",
    label: "确认",
    icon: UserCheck,
    traceStages: ["confirm"],
    pendingText: "等待人工终审节点",
    activeText: "等待人工确认或提交修改意见",
    doneText: "人工确认已完成"
  },
  {
    key: "download",
    label: "下载",
    icon: Download,
    traceStages: ["download", "export"],
    pendingText: "等待最终文件导出",
    activeText: "导出 Markdown/DOCX 并上传 MinIO",
    doneText: "最终文件可下载"
  }
];

function statusIndex(status: string) {
  const value = status.toLowerCase();
  if (["uploading", "uploaded"].includes(value)) {
    return 0;
  }
  if (["parsing", "parsed", "parsed_confirmed"].includes(value)) {
    return 1;
  }
  if (["processing", "generating", "generated"].includes(value)) {
    return 2;
  }
  if (["reviewing"].includes(value)) {
    return 3;
  }
  if (["human_review", "needs_revision", "draft_saved"].includes(value)) {
    return 4;
  }
  if (["approved", "finished"].includes(value)) {
    return 5;
  }
  if (["failed", "generation_failed"].includes(value)) {
    return 3;
  }
  return -1;
}

function readableStatus(status: string) {
  const labels: Record<string, string> = {
    idle: "待上传",
    uploading: "上传中",
    uploaded: "已上传",
    parsing: "解析招标文件",
    parsed: "解析完成",
    parsed_confirmed: "解析已确认",
    outline_ready: "可以生成",
    outline_review: "可以生成",
    outline_confirmed: "可以生成",
    processing: "准备生成",
    generating: "正在生成标书",
    generated: "生成完成",
    reviewing: "正在审查",
    human_review: "等待人工确认",
    draft_saved: "草稿已保存",
    needs_revision: "需要修正",
    approved: "已确认",
    finished: "已完成",
    failed: "失败",
    generation_failed: "生成失败"
  };
  return labels[status] ?? status;
}

function readableTraceMeta(meta: string) {
  return meta
    .replace("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro")
    .replace("deepseek-v4-pro", "DeepSeek V4 Pro");
}

function stageProgress(
  status: string,
  index: number,
  current: number,
  busy: boolean,
  elapsedSeconds: number
) {
  const value = status.toLowerCase();
  if (current > index) {
    return 100;
  }
  if (current < index || current === -1) {
    return 0;
  }

  if (busy && current === index) {
    const stageMaxProgress = [45, 55, 92, 90, 95, 98][index] ?? 92;
    return Math.min(stageMaxProgress, 32 + Math.floor(elapsedSeconds / 4) * 2);
  }

  const activeProgress: Record<string, number> = {
    uploading: 45,
    uploaded: 100,
    parsing: 55,
    parsed: 100,
    parsed_confirmed: 100,
    processing: 35,
    generating: 70,
    generated: 100,
    reviewing: 75,
    human_review: 85,
    needs_revision: 65,
    approved: 100,
    finished: 100,
    failed: 100,
    generation_failed: 100
  };
  return activeProgress[value] ?? 35;
}

function formatElapsed(seconds: number) {
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

function progressTone(status: string, complete: boolean, active: boolean) {
  const failed = ["failed", "generation_failed"].includes(status.toLowerCase());
  if (failed && active) {
    return "bg-danger";
  }
  if (complete) {
    return "bg-ok";
  }
  if (active) {
    return "bg-brand";
  }
  return "bg-line";
}

export function StatusRail({
  status,
  busy,
  traceEvents = []
}: {
  status: string;
  busy: boolean;
  traceEvents?: WorkflowTraceEvent[];
}) {
  const current = statusIndex(status);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    setElapsedSeconds(0);
    if (!busy) {
      return undefined;
    }

    const startedAt = Date.now();
    const interval = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    return () => window.clearInterval(interval);
  }, [busy, status]);

  function stageTrace(stage: Stage, complete: boolean, active: boolean) {
    const matched = traceEvents.filter((event) =>
      stage.traceStages.includes(event.stage)
    );
    if (matched.length) {
      return matched.slice(-3).map((event) => ({
        status: event.status,
        message: event.message,
        meta: [
          event.model_name,
          event.duration_ms ? `${event.duration_ms}ms` : "",
        ]
          .filter(Boolean)
          .join(" · ")
      }));
    }
    if (active) {
      const elapsed = busy ? `，已等待 ${formatElapsed(elapsedSeconds)}` : "";
      return [
        {
          status: "running",
          message: `${stage.activeText}${elapsed}`
        }
      ];
    }
    if (complete) {
      return [{ status: "done", message: stage.doneText }];
    }
    return [{ status: "pending", message: stage.pendingText }];
  }

  function traceDotClass(traceStatus: string) {
    if (traceStatus === "done") {
      return "bg-ok";
    }
    if (traceStatus === "failed") {
      return "bg-danger";
    }
    if (traceStatus === "running") {
      return "bg-brand";
    }
    return "bg-line";
  }

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[#1d1d1f]">实时状态</h2>
        <span className="rounded-full border border-black/[0.06] bg-white/70 px-3 py-1 text-xs font-medium text-[#6e6e73]">
          {readableStatus(status || "idle")}
        </span>
      </div>
      <ol className="space-y-3">
        {stages.map((stage, index) => {
          const complete = current > index;
          const active = current === index;
          const Icon = stage.icon;
          const progress = stageProgress(
            status,
            index,
            current,
            busy,
            elapsedSeconds
          );
          const traces = stageTrace(stage, complete, active);

          return (
            <li key={stage.label} className="space-y-2">
              <div className="flex items-center gap-3">
                <span
                  className={[
                    "grid h-8 w-8 shrink-0 place-items-center rounded-full border",
                    complete
                      ? "border-[#34c759] bg-[#34c759] text-white"
                      : active
                        ? "border-[#007aff]/20 bg-[#007aff]/10 text-[#007aff]"
                        : "border-black/[0.08] bg-white/52 text-[#8e8e93]"
                  ].join(" ")}
                >
                  {busy && active ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : complete ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : active ? (
                    <Icon className="h-4 w-4" />
                  ) : (
                    <Circle className="h-3 w-3" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={[
                        "text-sm",
                        complete || active ? "font-medium text-ink" : "text-muted"
                      ].join(" ")}
                    >
                      {stage.label}
                    </span>
                    <span className="w-10 text-right text-xs tabular-nums text-muted">
                      {progress}%
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/[0.06]">
                    <div
                      className={[
                        "h-full rounded-full transition-all duration-500",
                        progressTone(status, complete, active),
                        busy && active ? "animate-pulse" : ""
                      ].join(" ")}
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <div className="mt-2 space-y-1.5">
                    {traces.map((trace, traceIndex) => (
                      <div
                        key={`${stage.key}-${traceIndex}-${trace.message}`}
                        className="flex items-start gap-2 text-xs leading-5 text-muted"
                      >
                        <span
                          className={[
                            "mt-2 h-1.5 w-1.5 shrink-0 rounded-full",
                            traceDotClass(trace.status)
                          ].join(" ")}
                        />
                        <span>
                          {trace.message}
                          {"meta" in trace && trace.meta ? (
                            <span className="ml-1 text-[11px] text-muted">
                              {readableTraceMeta(trace.meta)}
                            </span>
                          ) : null}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function StatusProgressOverlay({
  open,
  status,
  busy,
  traceEvents = [],
  onDismiss
}: {
  open: boolean;
  status: string;
  busy: boolean;
  traceEvents?: WorkflowTraceEvent[];
  onDismiss?: () => void;
}) {
  const current = statusIndex(status);
  const activeIndex = current >= 0 ? current : 0;
  const activeStage = stages[activeIndex] ?? stages[0];
  const ActiveIcon = activeStage.icon;
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!open) {
      setElapsedSeconds(0);
      return undefined;
    }

    const startedAt = Date.now();
    const interval = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    return () => window.clearInterval(interval);
  }, [open, status]);

  if (!open) {
    return null;
  }

  const progress = stageProgress(
    status,
    activeIndex,
    activeIndex,
    busy,
    elapsedSeconds
  );
  const matched = traceEvents
    .filter((event) => activeStage.traceStages.includes(event.stage))
    .slice(-3);
  const activeMessage =
    matched.at(-1)?.message ||
    (progress >= 100
      ? activeStage.doneText
      : `${activeStage.activeText}，已等待 ${formatElapsed(elapsedSeconds)}`);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/55 px-4 backdrop-blur-2xl backdrop-saturate-50">
      <div className="absolute inset-0 bg-black/20" />
      <section className="ios-glass relative w-full max-w-[520px] rounded-[32px] border p-6 text-[#1d1d1f] shadow-[0_34px_90px_rgba(0,0,0,0.34)]">
        {onDismiss ? (
          <button
            type="button"
            title="关闭并返回工作台"
            className="absolute right-4 top-4 grid h-8 w-8 place-items-center rounded-full bg-black/[0.04] text-[#6e6e73] transition hover:bg-black/[0.08] hover:text-[#1d1d1f]"
            onClick={onDismiss}
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
        <div className="flex items-start gap-4">
          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-[18px] bg-[#007aff]/10 text-[#007aff]">
            {progress >= 100 ? (
              <CheckCircle2 className="h-6 w-6" />
            ) : busy ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : (
              <ActiveIcon className="h-6 w-6" />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[15px] font-semibold">{activeStage.label}</p>
                <p className="mt-0.5 text-xs text-[#6e6e73]">
                  {readableStatus(status || "idle")}
                </p>
              </div>
              <span className="text-xl font-semibold tabular-nums text-[#1d1d1f]">
                {progress}%
              </span>
            </div>
            <div className="mt-5 h-2 overflow-hidden rounded-full bg-black/[0.08]">
              <div
                className={[
                  "h-full rounded-full transition-all duration-500",
                  progress >= 100 ? "bg-[#34c759]" : "bg-[#007aff]"
                ].join(" ")}
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="mt-4 text-sm leading-6 text-[#3a3a3c]">
              {activeMessage}
            </p>
            {matched.length > 1 ? (
              <div className="mt-3 space-y-1.5 rounded-[18px] bg-white/48 px-3 py-2">
                {matched.slice(0, -1).map((event, index) => (
                  <p
                    key={`${event.stage}-${event.message}-${index}`}
                    className="line-clamp-1 text-xs text-[#6e6e73]"
                  >
                    {event.message}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
