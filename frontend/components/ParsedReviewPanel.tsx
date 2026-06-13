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
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          请确认项目事实、资质、评分项和废标条款；格式页由原招标文件直接复制生成。
        </p>
        <button
          type="button"
          disabled={!parsed || busy}
          className="inline-flex h-9 shrink-0 items-center gap-2 rounded-full bg-[#007aff] px-3.5 text-xs font-semibold text-white shadow-[0_10px_22px_rgba(0,122,255,0.18)] hover:bg-[#006ee6] disabled:cursor-not-allowed disabled:bg-[#b7d9ff] disabled:shadow-none"
          onClick={onSave}
        >
          <Save className="h-4 w-4" />
          确认解析
        </button>
      </div>

      <textarea
        value={value}
        disabled={!parsed || busy}
        onChange={(event) => onChange(event.target.value)}
        className="mt-3 min-h-[500px] w-full resize-y rounded-[20px] border border-black/[0.08] bg-white/62 p-3 font-mono text-xs leading-5 text-ink outline-none focus:border-[#007aff]"
      />
    </div>
  );
}
