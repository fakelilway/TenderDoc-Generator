"use client";

import { FileCheck2, Save } from "lucide-react";
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
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">解析与格式确认</h2>
          <p className="mt-1 text-xs text-muted">
            请确认项目事实、资质、评分项和废标条款；格式页由原招标文件直接复制生成。
          </p>
        </div>
        <button
          type="button"
          disabled={!parsed || busy}
          className="inline-flex h-9 items-center gap-2 rounded-full bg-[#007aff] px-3.5 text-xs font-semibold text-white shadow-[0_10px_22px_rgba(0,122,255,0.18)] hover:bg-[#006ee6] disabled:cursor-not-allowed disabled:bg-[#b7d9ff] disabled:shadow-none"
          onClick={onSave}
        >
          <Save className="h-4 w-4" />
          确认解析
        </button>
      </div>

      <div className="mt-4 rounded-[22px] border border-black/[0.08] bg-white/55 p-3">
        <div className="flex items-start gap-2">
          <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-ink">格式生成方式</p>
            <p className="mt-2 text-xs leading-5 text-muted">
              系统不再根据 LLM 总结重画投标文件格式。DOCX 招标文件使用 OOXML 原样复制；
              PDF 招标文件使用原页底图加可编辑文本层，生成失败则停止，不回退近似格式。
            </p>
          </div>
        </div>
      </div>
      <textarea
        value={value}
        disabled={!parsed || busy}
        onChange={(event) => onChange(event.target.value)}
        className="mt-3 min-h-64 w-full resize-y rounded-[20px] border border-black/[0.08] bg-white/62 p-3 font-mono text-xs leading-5 text-ink outline-none focus:border-[#007aff]"
      />
    </section>
  );
}
