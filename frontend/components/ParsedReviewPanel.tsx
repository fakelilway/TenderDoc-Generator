"use client";

import { CheckCircle2, Save, TriangleAlert } from "lucide-react";
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
  const parsedFromText = parseRequirements(value);
  const formatText = parsedFromText?.bid_format_requirements?.trim() || "";
  const formatLines = formatText
    .split("\n")
    .map((line) => line.replace(/^-\s*/, "").trim())
    .filter(Boolean);
  const hasFormatRequirements = formatLines.length > 0;

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">解析与格式确认</h2>
          <p className="mt-1 text-xs text-muted">
            投标文件格式会影响废标风险，必须由制作员确认后才能生成。
          </p>
        </div>
        <button
          type="button"
          disabled={!parsed || busy || !hasFormatRequirements}
          className="inline-flex h-9 items-center gap-2 rounded-full bg-[#007aff] px-3.5 text-xs font-semibold text-white shadow-[0_10px_22px_rgba(0,122,255,0.18)] hover:bg-[#006ee6] disabled:cursor-not-allowed disabled:bg-[#b7d9ff] disabled:shadow-none"
          onClick={onSave}
        >
          <Save className="h-4 w-4" />
          确认解析
        </button>
      </div>

      <div
        className={[
          "mt-4 rounded-[22px] border p-3",
          hasFormatRequirements
            ? "border-[#34c759]/20 bg-[#34c759]/10"
            : "border-[#ff9f0a]/20 bg-[#ff9f0a]/10"
        ].join(" ")}
      >
        <div className="flex items-start gap-2">
          {hasFormatRequirements ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
          ) : (
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-ink">投标文件格式要求</p>
            {hasFormatRequirements ? (
              <ul className="mt-2 max-h-48 space-y-1 overflow-auto text-xs leading-5 text-ink">
                {formatLines.map((line, index) => (
                  <li key={`${line}-${index}`} className="flex gap-2">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand" />
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs leading-5 text-ink">
                未识别到投标文件组成、表单、签字盖章、正副本、密封或电子标要求。
                请从招标文件补充到下方 JSON 的
                <code className="mx-1 rounded bg-white px-1 py-0.5">
                  bid_format_requirements
                </code>
                字段后再确认。
              </p>
            )}
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

function parseRequirements(value: string): TenderRequirements | null {
  try {
    return JSON.parse(value) as TenderRequirements;
  } catch {
    return null;
  }
}
