"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, BriefcaseBusiness, Check, Ruler } from "lucide-react";

import {
  getRolePerformanceRecommendations,
  saveRolePerformanceSelection
} from "@/lib/api";
import { EvidencePagePicker } from "@/components/EvidencePagePicker";
import type { PerformanceItem, PerformanceRecommendation } from "@/lib/types";

// 角色业绩勾选(多选):选派完项目经理/总工后,把此人名下(《类似项目信息表》里)的业绩列出来
// **全部人工手选**(用户2026-07-11拍板:不要默认全选)。勾中哪几条,生成时该角色的
// "近年完成的类似项目"表就只填哪几条;一条不勾 = 该表留白、证明扫描件也不附。

const ROLE_TEXT = {
  pm: {
    title: "项目经理业绩选择（多选）",
    subtitle: "候选＝选派的项目经理名下的项目",
    table: "项目经理近年完成的类似项目信息表",
    needFirst: "先在上方选派项目经理，再来勾选他名下的业绩。",
    iconColor: "bg-[#ff9500]/14 text-[#c2740d]"
  },
  td: {
    title: "项目总工业绩选择（多选）",
    subtitle: "项目总工＝技术负责人；候选＝选派人名下的项目",
    table: "项目总工近年完成的类似项目信息表",
    needFirst: "先在上方选派项目总工（技术负责人），再来勾选他名下的业绩。",
    iconColor: "bg-[#007aff]/14 text-[#0a6cff]"
  }
} as const;

function asItem(rec: PerformanceRecommendation): PerformanceItem {
  return {
    name: rec.name,
    year: rec.year,
    amount: rec.amount,
    type: rec.type,
    document_id: rec.document_id ?? null
  };
}

export function RolePerformancePanel({
  projectId,
  role,
  refreshToken = 0
}: {
  projectId: number;
  role: "pm" | "td";
  refreshToken?: number; // 外层选派/换人后 bump → 重拉此人名下候选
}) {
  const text = ROLE_TEXT[role];
  const [person, setPerson] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<PerformanceRecommendation[]>([]);
  const [roleHolders, setRoleHolders] = useState<{ name: string; count: number }[]>([]);
  // null = 服务端没存过勾选 = 一条都没勾(生成留白);全部人工手选,不做默认全选。
  const [selectedItems, setSelectedItems] = useState<Map<string, PerformanceItem> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // 重拉序号:换人后旧请求的响应作废;重拉期间(loaded=false)列表禁点,
  // 防止对着旧人的候选勾选、把旧人的业绩写进新人的勾选列。
  const seqRef = useRef(0);

  const refresh = useCallback(async () => {
    const seq = ++seqRef.current;
    setLoaded(false);
    try {
      const res = await getRolePerformanceRecommendations(projectId, role);
      if (seq !== seqRef.current) return; // 过期响应,丢弃
      setPerson(res.person);
      setRecommendations(res.recommendations);
      setRoleHolders(res.role_holders || []);
      setSelectedItems(
        res.selected === null
          ? null
          : new Map(res.selected.map((s) => [s.name, s]))
      );
      setError(null);
    } catch (caught) {
      if (seq !== seqRef.current) return;
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (seq === seqRef.current) setLoaded(true);
    }
  }, [projectId, role]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshToken]);

  // 生效的勾选集:没存过 = 一条都没勾(全部人工手选,不默认全选)
  const effective = useMemo(
    () => selectedItems ?? new Map<string, PerformanceItem>(),
    [selectedItems]
  );

  const toggle = useCallback(
    async (rec: PerformanceRecommendation) => {
      const next = new Map(effective);
      if (next.has(rec.name)) next.delete(rec.name);
      else next.set(rec.name, asItem(rec));
      setSelectedItems(next);
      setBusy(true);
      setError(null);
      try {
        // 保存按候选列表(台账序)排序:出表顺序=面板显示顺序,勾来勾去不改次序。
        // 不在候选里的旧勾选项(换人竞态等留下的幽灵)就势丢弃——它们不属于当前
        // 选派人,留着只会在生成时印出"只有项目名、其余全空"的错行。
        const ordered = recommendations
          .filter((r) => next.has(r.name))
          .map((r) => next.get(r.name)!);
        await saveRolePerformanceSelection(projectId, role, ordered);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        void refresh(); // 失败回滚到服务端真值
      } finally {
        setBusy(false);
      }
    },
    [projectId, role, effective, recommendations, refresh]
  );

  const picked = effective.size;
  const total = recommendations.length;

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`grid h-8 w-8 place-items-center rounded-full ${text.iconColor}`}>
            {role === "pm" ? (
              <BriefcaseBusiness className="h-4 w-4" />
            ) : (
              <Ruler className="h-4 w-4" />
            )}
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[#1d1d1f]">{text.title}</h2>
            <p className="text-[11px] text-[#8e8e93]">
              {person ? `已选派:${person} · ${text.subtitle}` : text.subtitle}
            </p>
          </div>
        </div>
        {person ? (
          <span
            className={[
              "shrink-0 rounded-full px-2.5 py-1 text-xs",
              picked === 0
                ? "bg-[#ff9500]/14 text-[#c2740d]"
                : "bg-[#34c759]/15 text-[#1f9d4d]"
            ].join(" ")}
          >
            已选 {picked} / 共{total}
          </span>
        ) : null}
      </div>

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      {person && total > 0 ? (
        <p
          className={[
            "mt-2 rounded-[10px] px-2.5 py-1.5 text-[11px]",
            picked === 0
              ? "bg-[#ff9500]/[0.08] text-[#c2740d]"
              : "bg-[#34c759]/[0.06] text-[#1f9d4d]"
          ].join(" ")}
        >
          {picked === 0
            ? `全部人工手选：勾中哪几条才填哪几条；现在一条没勾，生成时「${text.table}」留白、证明扫描件也不附。`
            : `勾中的 ${picked} 条会原样填进「${text.table}」，其证明扫描件一并附后。`}
        </p>
      ) : null}

      <div className="mt-3 max-h-[420px] space-y-1.5 overflow-auto">
        {loaded && !error && !person ? (
          <p className="rounded-[14px] border border-dashed border-black/[0.08] bg-white/54 px-3 py-3 text-center text-xs text-[#8e8e93]">
            {text.needFirst}
          </p>
        ) : null}
        {loaded && !error && person && total === 0 ? (
          <div className="rounded-[14px] border border-dashed border-[#ff9500]/40 bg-[#ff9500]/[0.05] px-3 py-3 text-xs">
            <p className="font-medium text-[#c2740d]">
              「{person}」在《类似项目信息表》47条里没当过{role === "pm" ? "项目经理" : "技术负责人"}
              ，生成时该表留白、不附证明。
            </p>
            {roleHolders.length ? (
              <p className="mt-1.5 text-[11px] leading-relaxed text-[#6e6e73]">
                表里当过{role === "pm" ? "项目经理" : "技术负责人（项目总工）"}的人：
                {roleHolders.map((h) => `${h.name}（${h.count}条）`).join("、")}
                。需要带业绩，请在上方改选派其中一位。
              </p>
            ) : null}
          </div>
        ) : null}
        {person
          ? recommendations.map((rec) => {
              const isSel = effective.has(rec.name);
              return (
                <div key={rec.name}>
                <button
                  type="button"
                  disabled={busy || !loaded}
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
                      isSel
                        ? "border-[#34c759] bg-[#34c759] text-white"
                        : "border-black/20 bg-white"
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
                    {(rec.matched?.length || rec.gaps?.length) ? (
                      <span className="mt-1 flex flex-wrap gap-1">
                        {(rec.matched || []).map((m) => (
                          <span
                            key={m}
                            className="rounded bg-[#34c759]/12 px-1.5 py-0.5 text-[10px] text-[#1f9d4d]"
                          >
                            {m}
                          </span>
                        ))}
                        {(rec.gaps || []).map((g) => (
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
                {isSel ? (
                  <EvidencePagePicker projectId={projectId} name={rec.name} />
                ) : null}
                </div>
              );
            })
          : null}
      </div>
    </section>
  );
}
