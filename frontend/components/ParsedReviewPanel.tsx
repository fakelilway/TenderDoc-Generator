"use client";

import { Save } from "lucide-react";
import type { TenderRequirements } from "@/lib/types";

type Props = {
  parsed: TenderRequirements | null;
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSave: () => void;
};

export function ParsedReviewPanel({
  parsed,
  value,
  busy,
  onChange,
  onSave
}: Props) {
  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">解析确认</h2>
        <button
          type="button"
          disabled={!parsed || busy}
          className="inline-flex h-8 items-center gap-2 rounded-md bg-brand px-3 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
          onClick={onSave}
        >
          <Save className="h-4 w-4" />
          保存
        </button>
      </div>
      <textarea
        value={value}
        disabled={!parsed || busy}
        onChange={(event) => onChange(event.target.value)}
        className="mt-3 min-h-64 w-full resize-y rounded-md border border-line bg-field p-3 font-mono text-xs leading-5 text-ink outline-none focus:border-brand"
      />
    </section>
  );
}
