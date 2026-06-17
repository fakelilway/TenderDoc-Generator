"use client";

import { useCallback, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Hand,
  Loader2,
  RefreshCw,
  XCircle
} from "lucide-react";

import { getProjectConformance } from "@/lib/api";
import type { ConformanceReportResponse, FillRequirement } from "@/lib/types";

// 逐空核对报告:读懂招标→每个空"找要求→核对我方→填/告警"。红=废标级、黄=预警、
// 绿=符合、灰=待人工。报告由后端实时跑(含 LLM 抽投标规格),故按钮触发而非自动拉。

type StatusStyle = {
  icon: typeof CheckCircle2;
  text: string;
  chip: string;
};

const STATUS: Record<string, StatusStyle> = {
  不符合: { icon: XCircle, text: "text-[#d8341c]", chip: "bg-[#ff3b30]/12 text-[#d8341c]" },
  缺料: { icon: AlertTriangle, text: "text-[#c2740d]", chip: "bg-[#ff9500]/14 text-[#c2740d]" },
  不一致: { icon: AlertTriangle, text: "text-[#c2740d]", chip: "bg-[#ff9500]/14 text-[#c2740d]" },
  符合: { icon: CheckCircle2, text: "text-[#1f9d4d]", chip: "bg-[#34c759]/12 text-[#1f9d4d]" },
  一致: { icon: CheckCircle2, text: "text-[#1f9d4d]", chip: "bg-[#34c759]/12 text-[#1f9d4d]" },
  待人工: { icon: Hand, text: "text-[#6e6e73]", chip: "bg-black/[0.06] text-[#6e6e73]" }
};

const STATUS_ORDER = ["不符合", "缺料", "不一致", "待人工", "符合", "一致"];

function styleOf(status: string): StatusStyle {
  return STATUS[status] ?? STATUS["待人工"];
}

export function ConformancePanel({ projectId }: { projectId: number }) {
  const [report, setReport] = useState<ConformanceReportResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await getProjectConformance(projectId));
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      setError(
        /parsed requirements/i.test(message)
          ? "先在「解析确认」完成招标解析,再跑核对。"
          : message
      );
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  const items = report?.items ?? [];
  const sorted = [...items].sort(
    (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)
  );

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-[#5856d6]/12 text-[#5856d6]">
            <ClipboardCheck className="h-4 w-4" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[#1d1d1f]">逐空核对报告</h2>
            <p className="text-[11px] text-[#8e8e93]">
              读懂招标 → 每个空「找要求→核对→填/告警」
            </p>
          </div>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void run()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#5856d6]/30 bg-[#5856d6]/10 px-3 py-1.5 text-xs font-medium text-[#5856d6] transition hover:bg-[#5856d6]/16 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : report ? (
            <RefreshCw className="h-3.5 w-3.5" />
          ) : null}
          {busy ? "核对中…" : report ? "重跑" : "跑核对"}
        </button>
      </div>

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      {report?.has_blocking ? (
        <div className="mt-3 flex items-center gap-2 rounded-[14px] border border-[#ff3b30]/25 bg-[#ff3b30]/[0.06] px-3 py-2 text-xs font-semibold text-[#d8341c]">
          <XCircle className="h-4 w-4" />
          有废标级问题(不符合招标硬性要求),务必人工核
        </div>
      ) : null}

      {busy ? (
        <p className="mt-3 text-xs text-[#8e8e93]">读懂招标 + 逐空核对中(含 LLM 抽规格,约十几秒)…</p>
      ) : null}

      {report && !busy ? (
        <div className="mt-3 space-y-1.5">
          <p className="text-[11px] text-[#8e8e93]">
            共 {items.length} 项 · 预警 {report.warning_count} · 待人工 {report.pending_count}
          </p>
          {sorted.map((item: FillRequirement) => {
            const style = styleOf(item.status);
            const Icon = style.icon;
            return (
              <div
                key={item.field}
                className="rounded-[14px] border border-black/[0.06] bg-white/56 px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold text-[#1d1d1f]">
                    <Icon className={`h-3.5 w-3.5 ${style.text}`} />
                    {item.field}
                  </p>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] ${style.chip}`}>
                    {item.status} → {item.action}
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-[#6e6e73]">
                  <span className="text-[#8e8e93]">出处</span> {item.source}
                </p>
                <p className="text-[11px] text-[#6e6e73]">
                  <span className="text-[#8e8e93]">要求</span> {item.required || "—"}
                  {item.our_value ? (
                    <>
                      {" "}
                      <span className="text-[#8e8e93]">· 我方</span> {item.our_value}
                    </>
                  ) : null}
                </p>
                {item.note ? (
                  <p className={`mt-0.5 text-[11px] ${style.text}`}>{item.note}</p>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {!report && !busy && !error ? (
        <p className="mt-3 rounded-[14px] border border-dashed border-black/[0.08] bg-white/54 px-3 py-3 text-center text-xs text-[#8e8e93]">
          点「跑核对」——系统读懂招标后,逐个该填的空核对「招标要什么 vs 我方有没有」,
          红=废标级、黄=预警、灰=待人工。
        </p>
      ) : null}
    </section>
  );
}
