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

          return (
            <li key={stage.label} className="flex items-center gap-3">
              <span
                className={[
                  "grid h-8 w-8 place-items-center rounded-md border",
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
              <span
                className={[
                  "text-sm",
                  complete || active ? "font-medium text-ink" : "text-muted"
                ].join(" ")}
              >
                {stage.label}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
