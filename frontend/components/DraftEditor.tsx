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
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          编辑 Markdown 正文，保存后生效。审查问题点击可跳转到对应行。
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || !markdown.trim()}
            className="inline-flex h-9 items-center gap-2 rounded-full border border-black/[0.06] bg-white/68 px-3.5 text-xs font-medium text-[#1d1d1f] hover:bg-white disabled:text-muted"
            onClick={onChecklist}
          >
            <FileCheck2 className="h-4 w-4" />
            清单
          </button>
          <button
            type="button"
            disabled={busy || !markdown.trim()}
            className="inline-flex h-9 items-center gap-2 rounded-full bg-[#007aff] px-3.5 text-xs font-semibold text-white shadow-[0_10px_22px_rgba(0,122,255,0.18)] hover:bg-[#006ee6] disabled:bg-[#b7d9ff] disabled:shadow-none"
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
        className="mt-3 min-h-[500px] w-full resize-y rounded-[20px] border border-black/[0.08] bg-white/62 p-4 font-mono text-xs leading-5 text-ink outline-none focus:border-[#007aff]"
      />
    </div>
  );
}
