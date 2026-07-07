"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Award, Check } from "lucide-react";

import {
  getPerformanceRecommendations,
  savePerformanceSelection
} from "@/lib/api";
import type {
  PerformanceItem,
  PerformanceRecommendation,
  PerformanceRequirement
} from "@/lib/types";

// 本项目类似业绩选择(多选):按招标"类似业绩 N 个/近X年/金额/同类"从台账推荐,勾选若干条,
// 生成时只插选中的业绩 + 其证明链(中标/合同/交工),不再一股脑全堆。

function reqText(req: PerformanceRequirement | null): string {
  if (!req) return "";
  const bits: string[] = [];
  if (req.since) bits.push(req.since);
  if (req.category) bits.push(req.category);
  if (req.min_amount_wan) bits.push(`≥${req.min_amount_wan}万`);
  if (req.min_count) bits.push(`需${req.min_count}个`);
  return bits.length ? `招标要求:${bits.join(" / ")}` : "招标未明确类似业绩要求,列全部台账供选";
}

export function PerformancePanel({
  projectId,
  refreshToken = 0
}: {
  projectId: number;
  refreshToken?: number; // 外层选派项目经理后 bump → 重拉服务端自动带出的选中业绩
}) {
  const [requirement, setRequirement] = useState<PerformanceRequirement | null>(null);
  const [recommendations, setRecommendations] = useState<PerformanceRecommendation[]>([]);
  // 全量选中项(名字→完整条目):不能只存名字集合再从推荐列表反查——自动带出的业绩
  // 可能不在推荐列表里(推荐来自台账打分截断),那样任意一次勾选就会把它们静默冲掉
  const [selectedItems, setSelectedItems] = useState<Map<string, PerformanceItem>>(new Map());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await getPerformanceRecommendations(projectId);
      setRequirement(res.requirement);
      setRecommendations(res.recommendations);
      setSelectedItems(new Map((res.selected || []).map((s) => [s.name, s])));
      setError(null);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      setError(
        /parsed requirements/i.test(message)
          ? "先在「解析确认」完成招标解析,再来选择类似业绩。"
          : message
      );
    } finally {
      setLoaded(true);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshToken]);

  const toggle = useCallback(
    async (rec: PerformanceRecommendation) => {
      const next = new Map(selectedItems);
      if (next.has(rec.name)) next.delete(rec.name);
      else
        next.set(rec.name, {
          name: rec.name,
          year: rec.year,
          amount: rec.amount,
          type: rec.type,
          document_id: rec.document_id ?? null
        });
      setSelectedItems(next);
      setBusy(true);
      setError(null);
      try {
        await savePerformanceSelection(projectId, Array.from(next.values()));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        void refresh(); // 失败回滚到服务端真值
      } finally {
        setBusy(false);
      }
    },
    [projectId, selectedItems, refresh]
  );

  const need = requirement?.min_count || 0;
  const picked = selectedItems.size;

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-[#34c759]/14 text-[#1f9d4d]">
            <Award className="h-4 w-4" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[#1d1d1f]">类似业绩选择（多选）</h2>
            <p className="text-[11px] text-[#8e8e93]">
              {reqText(requirement)}
            </p>
          </div>
        </div>
        <span
          className={[
            "shrink-0 rounded-full px-2.5 py-1 text-xs",
            need && picked < need
              ? "bg-[#ff9500]/14 text-[#c2740d]"
              : "bg-[#34c759]/15 text-[#1f9d4d]"
          ].join(" ")}
        >
          已选 {picked}
          {need ? ` / 需${need}` : ""}
        </span>
      </div>

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      <p className="mt-2 rounded-[10px] bg-[#34c759]/[0.06] px-2.5 py-1.5 text-[11px] text-[#1f9d4d]">
        选中的业绩会原样填进「投标人近年完成的类似项目信息表」，证明图片一并带上。
      </p>

      <div className="mt-3 max-h-[420px] space-y-1.5 overflow-auto">
        {loaded && !error && recommendations.length === 0 ? (
          <p className="rounded-[14px] border border-dashed border-black/[0.08] bg-white/54 px-3 py-3 text-center text-xs text-[#8e8e93]">
            档案库里没有类似项目信息表记录。可让员工整理后重导入。
          </p>
        ) : null}
        {recommendations.map((rec) => {
          const isSel = selectedItems.has(rec.name);
          return (
            <button
              key={rec.name}
              type="button"
              disabled={busy}
              onClick={() => void toggle(rec)}
              className={[
                "flex w-full items-start gap-2.5 rounded-[14px] border px-3 py-2 text-left transition disabled:opacity-60",
                isSel
                  ? "border-[#34c759]/40 bg-[#34c759]/[0.08]"
                  : "border-black/[0.06] bg-white/56 hover:border-[#34c759]/30"
              ].join(" ")}
            >
              <span
                className={[
                  "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border",
                  isSel ? "border-[#34c759] bg-[#34c759] text-white" : "border-black/20 bg-white"
                ].join(" ")}
              >
                {isSel ? <Check className="h-3 w-3" /> : null}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-semibold text-[#1d1d1f]">
                  {rec.name}
                </span>
                <span className="block truncate text-[11px] text-[#6e6e73]">
                  {rec.amount || "—"} · {rec.year || "—"} · {rec.type || "—"}
                </span>
                {rec.matched.length || rec.gaps.length ? (
                  <span className="mt-1 flex flex-wrap gap-1">
                    {rec.matched.map((m) => (
                      <span
                        key={m}
                        className="rounded bg-[#34c759]/12 px-1.5 py-0.5 text-[10px] text-[#1f9d4d]"
                      >
                        {m}
                      </span>
                    ))}
                    {rec.gaps.map((g) => (
                      <span
                        key={g}
                        className="inline-flex items-center gap-0.5 rounded bg-[#ff9500]/14 px-1.5 py-0.5 text-[10px] text-[#c2740d]"
                      >
                        <AlertTriangle className="h-2.5 w-2.5" />
                        {g}
                      </span>
                    ))}
                  </span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
