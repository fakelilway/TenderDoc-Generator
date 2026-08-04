"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Check, HardHat, Ruler } from "lucide-react";

import {
  getPersonnelRecommendations,
  getTechDirectorRecommendations,
  savePersonnelSelection,
  saveTechDirectorSelection
} from "@/lib/api";
import type { PersonnelMember, PMRecommendation, PMSelectionResponse } from "@/lib/types";

// 本项目选派:项目经理(看建造师证)+ 项目总工(看职称)。按招标要求从公司名册推荐匹配候选,
// 选定后自动填进商务卷(投标人基本情况表 + 项目管理机构人员组成表)+ 证件插图按选定人取。

function certText(member: PersonnelMember): string {
  const certs = member.builder_certs
    .map((c) => `${c.level}${c.specialty ? `/${c.specialty}` : ""}`)
    .join("、");
  return certs || "无建造师证";
}

function sameMember(a: PersonnelMember | null, b: PersonnelMember | null): boolean {
  if (!a || !b) return false;
  if (a.id_number && b.id_number) return a.id_number === b.id_number;
  return a.name === b.name;
}

type RoleConfig = {
  title: string;
  iconColor: string;
  icon: ReactNode;
  fetchRecs: (
    projectId: number
  ) => Promise<{ requirement: unknown; recommendations: PMRecommendation[]; selected: PersonnelMember | null }>;
  saveSel: (projectId: number, member: PersonnelMember | null) => Promise<PMSelectionResponse>;
  selectedKey: "project_manager" | "tech_director";
  reqText: (requirement: unknown) => string;
  emptyHint: string;
};

function RoleSelector({
  projectId,
  role,
  onSelected
}: {
  projectId: number;
  role: RoleConfig;
  onSelected?: () => void;
}) {
  const [reqText, setReqText] = useState<string>("");
  const [recommendations, setRecommendations] = useState<PMRecommendation[]>([]);
  const [selected, setSelected] = useState<PersonnelMember | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await role.fetchRecs(projectId);
      setReqText(role.reqText(res.requirement));
      setRecommendations(res.recommendations);
      setSelected(res.selected);
      setError(null);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      setError(
        /parsed requirements/i.test(message)
          ? `先在「解析确认」完成招标解析,再来选派${role.title}。`
          : message
      );
    } finally {
      setLoaded(true);
    }
  }, [projectId, role]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const choose = useCallback(
    async (member: PersonnelMember | null) => {
      setBusy(true);
      setError(null);
      try {
        const res = await role.saveSel(projectId, member);
        setSelected((res.selected?.[role.selectedKey] as PersonnelMember) ?? null);
        onSelected?.(); // 通知外层:业绩跟经理走,业绩面板要刷新显示自动带出的选中项
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
      }
    },
    [projectId, role, onSelected]
  );

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`grid h-8 w-8 place-items-center rounded-full ${role.iconColor}`}>
            {role.icon}
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[#1d1d1f]">{role.title}选派</h2>
            <p className="text-[11px] text-[#8e8e93]">{reqText}</p>
          </div>
        </div>
        <span className="shrink-0 rounded-full bg-black/[0.05] px-2.5 py-1 text-xs text-[#6e6e73]">
          {recommendations.length} 候选
        </span>
      </div>

      {selected ? (
        <div className="mt-3 flex items-center justify-between gap-3 rounded-[16px] border border-[#34c759]/30 bg-[#34c759]/[0.08] px-3 py-2.5">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[#1f9d4d]">已选派:{selected.name}</p>
            <p className="truncate text-[11px] text-[#6e6e73]">
              {certText(selected)}
              {selected.title ? ` · ${selected.title}` : ""}
            </p>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => void choose(null)}
            className="shrink-0 rounded-full border border-black/[0.08] bg-white/70 px-3 py-1 text-xs text-[#6e6e73] transition hover:bg-white disabled:opacity-40"
          >
            取消
          </button>
        </div>
      ) : null}

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      <div className="mt-3 max-h-[360px] space-y-1.5 overflow-auto">
        {loaded && !error && recommendations.length === 0 ? (
          <p className="rounded-[14px] border border-dashed border-black/[0.08] bg-white/54 px-3 py-3 text-center text-xs text-[#8e8e93]">
            {role.emptyHint}
          </p>
        ) : null}
        {recommendations.map((rec) => {
          const isSel = sameMember(selected, rec.member);
          return (
            <div
              key={`${rec.member.name}-${rec.member.id_number}`}
              className={[
                "rounded-[14px] border px-3 py-2 transition",
                isSel ? "border-[#34c759]/30 bg-[#34c759]/[0.06]" : "border-black/[0.06] bg-white/56"
              ].join(" ")}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className={`text-xs font-semibold ${rec.has_resume_template ? "text-[#1f9d4d]" : "text-[#1d1d1f]"}`}>
                    {rec.member.name}
                    {rec.has_resume_template ? (
                      <span className="ml-1 rounded bg-[#34c759]/14 px-1.5 py-0.5 text-[10px] font-normal text-[#1f9d4d]">
                        有简历模版
                      </span>
                    ) : (
                      <span className="ml-1 rounded bg-[#ff9500]/14 px-1.5 py-0.5 text-[10px] font-normal text-[#c2740d]">
                        缺少简历
                      </span>
                    )}
                    <span className="ml-1.5 rounded bg-black/[0.05] px-1.5 py-0.5 text-[10px] font-normal text-[#8e8e93]">
                      {rec.member.source}
                    </span>
                  </p>
                  <p className="truncate text-[11px] text-[#6e6e73]">
                    {certText(rec.member)}
                    {rec.member.title ? ` · ${rec.member.title}` : ""}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={busy || isSel}
                  onClick={() => void choose(rec.member)}
                  className={[
                    "inline-flex shrink-0 items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition disabled:opacity-50",
                    isSel
                      ? "bg-[#34c759]/15 text-[#1f9d4d]"
                      : "border border-[#007aff]/30 bg-[#007aff]/10 text-[#007aff] hover:bg-[#007aff]/16"
                  ].join(" ")}
                >
                  {isSel ? (
                    <>
                      <Check className="h-3 w-3" /> 已选
                    </>
                  ) : (
                    "选派"
                  )}
                </button>
              </div>
              {rec.matched.length || rec.gaps.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {rec.matched.map((m) => (
                    <span key={m} className="rounded bg-[#34c759]/12 px-1.5 py-0.5 text-[10px] text-[#1f9d4d]">
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
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

const PM_ROLE: RoleConfig = {
  title: "项目经理",
  iconColor: "bg-[#ff9500]/14 text-[#c2740d]",
  icon: <HardHat className="h-4 w-4" />,
  fetchRecs: (pid) => getPersonnelRecommendations(pid),
  saveSel: (pid, m) => savePersonnelSelection(pid, m),
  selectedKey: "project_manager",
  reqText: (r) => {
    const req = r as { builder_level?: string; builder_specialty?: string; requires_safety_b?: boolean };
    return req && (req.builder_level || req.builder_specialty)
      ? `招标要求:${req.builder_level || "等级不限"}${req.builder_specialty ? ` / ${req.builder_specialty}` : ""}${req.requires_safety_b ? " / 需安全B证" : ""}`
      : "招标未明确项目经理要求,列全部建造师候选供选派";
  },
  emptyHint: "名册里没有符合要求的项目经理候选。可在公司证件库补充建造师后重导名册。"
};

const TECH_ROLE: RoleConfig = {
  title: "项目总工",
  iconColor: "bg-[#007aff]/14 text-[#0a6cff]",
  icon: <Ruler className="h-4 w-4" />,
  fetchRecs: (pid) => getTechDirectorRecommendations(pid),
  saveSel: (pid, m) => saveTechDirectorSelection(pid, m),
  selectedKey: "tech_director",
  reqText: (r) => {
    const req = r as { title_level?: string; specialty?: string; requires_registration?: boolean };
    return req && (req.title_level || req.specialty)
      ? `招标要求:${req.title_level || "职称不限"}${req.specialty ? ` / ${req.specialty}` : ""}${req.requires_registration ? " / 需注册建造师" : ""}`
      : "招标未明确总工要求,列有职称的候选供选派";
  },
  emptyHint: "名册里没有符合要求的总工候选。可在公司证件库补充职称证后重导名册。"
};

// 拆开导出:工作区里两个选派块之间要各插一块"该角色业绩勾选"面板(RolePerformancePanel),
// 顺序=公司业绩→选经理→勾经理业绩→选总工→勾总工业绩,故不能捆在一个面板里渲染。
export function PmRoleSelector({
  projectId,
  onSelected
}: {
  projectId: number;
  onSelected?: () => void;
}) {
  return <RoleSelector projectId={projectId} role={PM_ROLE} onSelected={onSelected} />;
}

export function TechRoleSelector({
  projectId,
  onSelected
}: {
  projectId: number;
  onSelected?: () => void;
}) {
  return <RoleSelector projectId={projectId} role={TECH_ROLE} onSelected={onSelected} />;
}

export function PersonnelPanel({
  projectId,
  onPmSelected
}: {
  projectId: number;
  onPmSelected?: () => void;
}) {
  return (
    <div className="space-y-3">
      <PmRoleSelector projectId={projectId} onSelected={onPmSelected} />
      <TechRoleSelector projectId={projectId} />
    </div>
  );
}
