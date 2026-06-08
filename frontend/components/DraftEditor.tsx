"use client";

import { FileCheck2, Save } from "lucide-react";

type Props = {
  markdown: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSave: () => void;
  onChecklist: () => void;
};

export function DraftEditor({
  markdown,
  busy,
  onChange,
  onSave,
  onChecklist
}: Props) {
  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">正文编辑</h2>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || !markdown.trim()}
            className="inline-flex h-8 items-center gap-2 rounded-md border border-line bg-white px-3 text-xs font-medium text-ink hover:bg-field disabled:text-muted"
            onClick={onChecklist}
          >
            <FileCheck2 className="h-4 w-4" />
            清单
          </button>
          <button
            type="button"
            disabled={busy || !markdown.trim()}
            className="inline-flex h-8 items-center gap-2 rounded-md bg-brand px-3 text-xs font-semibold text-white hover:bg-blue-700 disabled:bg-blue-300"
            onClick={onSave}
          >
            <Save className="h-4 w-4" />
            保存
          </button>
        </div>
      </div>
      <textarea
        value={markdown}
        onChange={(event) => onChange(event.target.value)}
        className="mt-3 min-h-[520px] w-full resize-y rounded-md border border-line bg-field p-3 font-mono text-xs leading-5 text-ink outline-none focus:border-brand"
      />
    </section>
  );
}
