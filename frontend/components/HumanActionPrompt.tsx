"use client";

import { AlertCircle, CheckCircle2, Loader2, PencilLine, Play, X } from "lucide-react";

type PromptAction = {
  label: string;
  tone?: "primary" | "success" | "neutral";
  icon?: "check" | "edit" | "play";
  disabled?: boolean;
  onClick: () => void;
};

type Props = {
  open: boolean;
  title: string;
  message: string;
  busy: boolean;
  actions: PromptAction[];
  onClose: () => void;
};

export function HumanActionPrompt({
  open,
  title,
  message,
  busy,
  actions,
  onClose
}: Props) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-lg rounded-lg border border-line bg-panel shadow-panel">
        <div className="flex min-h-12 items-center justify-between border-b border-line px-4">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-brand" />
            <h2 className="text-sm font-semibold text-ink">{title}</h2>
          </div>
          <button
            type="button"
            title="关闭"
            className="grid h-8 w-8 place-items-center rounded-md border border-line text-muted hover:bg-field"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4 p-4">
          <p className="text-sm leading-6 text-muted">{message}</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              className="inline-flex h-10 items-center justify-center rounded-md border border-line px-4 text-sm font-medium text-ink hover:bg-field"
              onClick={onClose}
            >
              稍后处理
            </button>
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                disabled={busy || action.disabled}
                className={[
                  "inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold disabled:cursor-not-allowed",
                  action.tone === "success"
                    ? "bg-ok text-white hover:bg-green-700 disabled:bg-green-300"
                    : action.tone === "neutral"
                      ? "border border-line bg-white text-ink hover:bg-field disabled:text-muted"
                      : "bg-brand text-white hover:bg-blue-700 disabled:bg-blue-300"
                ].join(" ")}
                onClick={action.onClick}
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <PromptIcon icon={action.icon} />
                )}
                {action.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function PromptIcon({ icon }: { icon?: PromptAction["icon"] }) {
  if (icon === "check") {
    return <CheckCircle2 className="h-4 w-4" />;
  }
  if (icon === "edit") {
    return <PencilLine className="h-4 w-4" />;
  }
  if (icon === "play") {
    return <Play className="h-4 w-4" />;
  }
  return null;
}
