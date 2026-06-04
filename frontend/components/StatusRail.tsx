import {
  CheckCircle2,
  Circle,
  Download,
  FileCheck2,
  FileText,
  Loader2,
  ShieldCheck,
  UploadCloud,
  UserCheck
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type Stage = {
  label: string;
  icon: LucideIcon;
};

const stages: Stage[] = [
  { label: "上传", icon: UploadCloud },
  { label: "解析", icon: FileText },
  { label: "生成", icon: FileCheck2 },
  { label: "审查", icon: ShieldCheck },
  { label: "确认", icon: UserCheck },
  { label: "下载", icon: Download }
];

function statusIndex(status: string) {
  const value = status.toLowerCase();
  if (["uploading", "uploaded"].includes(value)) {
    return 0;
  }
  if (["parsing", "parsed"].includes(value)) {
    return 1;
  }
  if (["processing", "generating", "generated"].includes(value)) {
    return 2;
  }
  if (["reviewing"].includes(value)) {
    return 3;
  }
  if (["human_review", "needs_revision"].includes(value)) {
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

function stageProgress(status: string, index: number, current: number) {
  const value = status.toLowerCase();
  if (current > index) {
    return 100;
  }
  if (current < index || current === -1) {
    return 0;
  }

  const activeProgress: Record<string, number> = {
    uploading: 45,
    uploaded: 100,
    parsing: 55,
    parsed: 100,
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
  busy
}: {
  status: string;
  busy: boolean;
}) {
  const current = statusIndex(status);

  return (
    <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">实时状态</h2>
        <span className="rounded-md border border-line bg-field px-2 py-1 text-xs font-medium text-muted">
          {status || "idle"}
        </span>
      </div>
      <ol className="space-y-3">
        {stages.map((stage, index) => {
          const complete = current > index;
          const active = current === index;
          const Icon = stage.icon;
          const progress = stageProgress(status, index, current);

          return (
            <li key={stage.label} className="space-y-2">
              <div className="flex items-center gap-3">
                <span
                  className={[
                    "grid h-8 w-8 shrink-0 place-items-center rounded-md border",
                    complete
                      ? "border-ok bg-ok text-white"
                      : active
                        ? "border-brand bg-blue-50 text-brand"
                        : "border-line bg-field text-muted"
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
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-field">
                    <div
                      className={[
                        "h-full rounded-full transition-all duration-500",
                        progressTone(status, complete, active),
                        busy && active ? "animate-pulse" : ""
                      ].join(" ")}
                      style={{ width: `${progress}%` }}
                    />
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
