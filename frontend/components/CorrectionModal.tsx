"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, PencilLine, X } from "lucide-react";

export function CorrectionModal({
  open,
  busy,
  onClose,
  onSubmit
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onSubmit: (approved: boolean, note: string) => void;
}) {
  const [note, setNote] = useState("");

  useEffect(() => {
    if (open) {
      setNote("");
    }
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-xl rounded-lg border border-line bg-panel shadow-panel">
        <div className="flex h-12 items-center justify-between border-b border-line px-4">
          <div className="flex items-center gap-2">
            <PencilLine className="h-4 w-4 text-brand" />
            <h2 className="text-sm font-semibold text-ink">人工修正</h2>
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
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            className="min-h-40 w-full resize-y rounded-md border border-line bg-field p-3 text-sm leading-6 text-ink"
            placeholder="修正意见"
          />
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              disabled={busy}
              className="inline-flex h-10 items-center justify-center rounded-md border border-line px-4 text-sm font-medium text-ink hover:bg-field disabled:cursor-not-allowed"
              onClick={() => onSubmit(false, note)}
            >
              保存修正
            </button>
            <button
              type="button"
              disabled={busy}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-ok px-4 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-green-300"
              onClick={() => onSubmit(true, note)}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              应用并批准
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
