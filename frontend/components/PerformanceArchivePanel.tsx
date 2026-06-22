"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  FileWarning,
  ImageIcon,
  Loader2,
  Pencil,
  X
} from "lucide-react";

import {
  getKnowledgeDocumentPreview,
  getPerformanceArchive,
  reassignPerformanceEvidence,
  renamePerformanceEvidence
} from "@/lib/api";
import { getStoredSession } from "@/lib/auth";
import type {
  PerformanceArchive,
  PerformanceEvidenceDoc,
  PerformanceLedger
} from "@/lib/types";

const EVIDENCE_ORDER = ["中标通知书", "合同", "交工验收"];

type Filter = "all" | "complete" | "review" | "claim" | "gap";

function shortName(name: string): string {
  const stripped = name.replace(/^\d+[-#＃]+/, "").trim();
  return stripped.length > 18 ? `${stripped.slice(0, 18)}…` : stripped;
}

function cleanLabel(evidenceProject: string, doc: PerformanceEvidenceDoc): string {
  return `【业绩·${shortName(evidenceProject)}】${doc.evidence_type}_${String(
    (doc.evidence_seq ?? 0) + 1
  ).padStart(2, "0")}`;
}

export function PerformanceArchivePanel() {
  const session = getStoredSession();
  const canEdit = session?.role === "admin";

  const [archive, setArchive] = useState<PerformanceArchive | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busyId, setBusyId] = useState<number | string | null>(null);

  // 图片预览
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewName, setPreviewName] = useState<string>("");
  const [previewLoadingId, setPreviewLoadingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setArchive(await getPerformanceArchive());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "业绩档案加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 所有项目名(供"改归属/认领"下拉选择)
  const allProjectNames = useMemo(() => {
    if (!archive) return [];
    const names = new Set<string>();
    archive.ledger_all.forEach((l) => names.add(l.name));
    archive.matched.forEach((m) => names.add(m.ledger.name));
    archive.evidence_only.forEach((e) => names.add(e.evidence_project));
    return Array.from(names).sort();
  }, [archive]);

  async function preview(doc: PerformanceEvidenceDoc) {
    setPreviewLoadingId(doc.document_id);
    try {
      const res = await getKnowledgeDocumentPreview(doc.document_id);
      setPreviewUrl(res.preview_url ?? null);
      setPreviewName(res.file_name);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "预览失败");
    } finally {
      setPreviewLoadingId(null);
    }
  }

  async function doReassign(
    key: string | number,
    docIds: number[],
    target: string
  ) {
    if (!target.trim() || docIds.length === 0) return;
    setBusyId(key);
    try {
      await reassignPerformanceEvidence(docIds, target.trim());
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "改归属失败");
    } finally {
      setBusyId(null);
    }
  }

  async function doRename(docId: number, title: string) {
    setBusyId(docId);
    try {
      await renamePerformanceEvidence(docId, title);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "改名失败");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-line bg-white px-4 py-6 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin" />
        正在加载业绩档案…
      </div>
    );
  }
  if (error && !archive) {
    return (
      <div className="rounded-md border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-danger">
        {error}
      </div>
    );
  }
  if (!archive) return null;

  const s = archive.stats;
  const tabs: { key: Filter; label: string; count: number }[] = [
    { key: "all", label: "全部", count: s.ledger_total + s.evidence_only },
    { key: "complete", label: "✅ 证据链完整", count: s.matched_complete_chain },
    { key: "review", label: "⚠️ 待确认", count: s.matched_need_review },
    { key: "claim", label: "📷 待认领", count: s.evidence_only },
    { key: "gap", label: "📄 缺证明", count: s.ledger_only }
  ];

  const showMatchedComplete = filter === "all" || filter === "complete";
  const showMatchedReview = filter === "all" || filter === "review";
  const showClaim = filter === "all" || filter === "claim";
  const showGap = filter === "all" || filter === "gap";

  return (
    <section className="space-y-3">
      {/* 体检条 */}
      <div className="rounded-lg border border-line bg-white p-3 text-xs text-muted">
        台账 <b className="text-ink">{s.ledger_total}</b> 个 · 证明{" "}
        <b className="text-ink">{s.evidence_projects}</b> 个项目 /{" "}
        <b className="text-ink">{s.evidence_images}</b> 张图 · 已配对{" "}
        <b className="text-ok">{s.matched}</b>(完整链 {s.matched_complete_chain})
      </div>

      {error ? (
        <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-danger">
          {error}
        </div>
      ) : null}

      {/* 筛选标签 */}
      <div className="flex flex-wrap gap-1.5">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setFilter(t.key)}
            className={[
              "rounded-full border px-3 py-1 text-xs transition-colors",
              filter === t.key
                ? "border-brand bg-blue-50 font-medium text-brand"
                : "border-line bg-field text-muted hover:border-brand hover:text-ink"
            ].join(" ")}
          >
            {t.label} {t.count}
          </button>
        ))}
      </div>

      {!canEdit ? (
        <p className="rounded-md border border-line bg-field px-3 py-2 text-xs text-muted">
          查看模式：改归属 / 认领 / 改名需要管理员账户。
        </p>
      ) : null}

      <div className="space-y-2">
        {/* 已配对(完整链 + 待确认) */}
        {archive.matched
          .filter((m) =>
            m.complete_chain ? showMatchedComplete : showMatchedReview
          )
          .map((m) => (
            <ProjectCard
              key={`m-${m.ledger.document_id}-${m.evidence_project}`}
              title={m.ledger.name}
              ledger={m.ledger}
              evidence={m.evidence}
              evidenceProject={m.evidence_project}
              badge={
                m.complete_chain
                  ? { tone: "ok", icon: <CheckCircle2 className="h-3.5 w-3.5" />, text: "证据链完整" }
                  : {
                      tone: "warn",
                      icon: <AlertTriangle className="h-3.5 w-3.5" />,
                      text: `待确认 ${(m.score * 100).toFixed(0)}%`
                    }
              }
              note={
                m.complete_chain
                  ? undefined
                  : `证明文件夹名「${m.evidence_project}」与台账对得勉强，请扫一眼是否同一项目`
              }
              canEdit={canEdit}
              busyId={busyId}
              previewLoadingId={previewLoadingId}
              allProjectNames={allProjectNames}
              onPreview={preview}
              onMove={(docId, target) => doReassign(docId, [docId], target)}
              onRename={doRename}
            />
          ))}

        {/* 待认领(有证明，对不上台账) */}
        {showClaim &&
          archive.evidence_only.map((e) => (
            <ClaimCard
              key={`c-${e.evidence_project}`}
              group={e}
              ledgerOptions={archive.ledger_all}
              canEdit={canEdit}
              busy={busyId === e.evidence_project}
              previewLoadingId={previewLoadingId}
              onPreview={preview}
              onClaim={(target) =>
                doReassign(
                  e.evidence_project,
                  Object.values(e.evidence).flat().map((d) => d.document_id),
                  target
                )
              }
            />
          ))}

        {/* 缺证明(有台账，没证明) */}
        {showGap &&
          archive.ledger_only.map((l) => (
            <div
              key={`g-${l.document_id}`}
              className="flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-2"
            >
              <FileWarning className="h-4 w-4 shrink-0 text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{l.name}</p>
                <p className="text-xs text-muted">
                  {l.year} · {l.amount} · 项目经理 {l.manager || "—"}
                </p>
              </div>
              <span className="shrink-0 rounded-full bg-field px-2 py-0.5 text-xs text-muted">
                缺扫描件
              </span>
            </div>
          ))}
      </div>

      {/* 预览灯箱 */}
      {previewUrl ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
          onClick={() => setPreviewUrl(null)}
        >
          <div
            className="max-h-[90vh] max-w-3xl overflow-auto rounded-lg bg-white p-3"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="truncate text-xs font-medium text-ink">{previewName}</p>
              <button
                type="button"
                onClick={() => setPreviewUrl(null)}
                className="grid h-7 w-7 place-items-center rounded-md border border-line text-muted hover:bg-field"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={previewUrl} alt={previewName} className="max-h-[78vh] rounded-md object-contain" />
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Bundle({
  evidence,
  evidenceProject,
  canEdit,
  busyId,
  previewLoadingId,
  allProjectNames,
  onPreview,
  onMove,
  onRename
}: {
  evidence: Record<string, PerformanceEvidenceDoc[]>;
  evidenceProject: string;
  canEdit: boolean;
  busyId: number | string | null;
  previewLoadingId: number | null;
  allProjectNames?: string[];
  onPreview: (doc: PerformanceEvidenceDoc) => void;
  onMove?: (docId: number, target: string) => void;
  onRename?: (docId: number, title: string) => void;
}) {
  const [editId, setEditId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [moveId, setMoveId] = useState<number | null>(null);

  const types = Object.keys(evidence).sort(
    (a, b) => EVIDENCE_ORDER.indexOf(a) - EVIDENCE_ORDER.indexOf(b)
  );

  return (
    <div className="mt-2 space-y-1.5">
      {types.map((type) => (
        <div key={type} className="flex flex-wrap items-center gap-1.5">
          <span className="shrink-0 text-xs font-medium text-muted">{type}</span>
          {evidence[type]
            .slice()
            .sort((a, b) => a.evidence_seq - b.evidence_seq)
            .map((doc) => (
              <span
                key={doc.document_id}
                className="inline-flex items-center gap-1 rounded-full border border-line bg-field px-2 py-0.5 text-xs text-ink"
              >
                {editId === doc.document_id ? (
                  <>
                    <input
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      className="h-6 w-40 rounded border border-line bg-white px-1 text-xs"
                      autoFocus
                    />
                    <button
                      type="button"
                      title="保存"
                      onClick={() => {
                        onRename?.(doc.document_id, editText);
                        setEditId(null);
                      }}
                      className="text-ok"
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" title="取消" onClick={() => setEditId(null)}>
                      <X className="h-3.5 w-3.5 text-muted" />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onPreview(doc)}
                      className="inline-flex items-center gap-1 hover:text-brand"
                      title="查看原图"
                    >
                      {previewLoadingId === doc.document_id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <ImageIcon className="h-3 w-3" />
                      )}
                      {cleanLabel(evidenceProject, doc)}
                    </button>
                    {canEdit ? (
                      <>
                        <button
                          type="button"
                          title="改名"
                          onClick={() => {
                            setEditId(doc.document_id);
                            setEditText(cleanLabel(evidenceProject, doc));
                          }}
                          className="text-muted hover:text-ink"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        {onMove ? (
                          <button
                            type="button"
                            title="挪到别的项目(改归属)"
                            onClick={() =>
                              setMoveId(moveId === doc.document_id ? null : doc.document_id)
                            }
                            className="text-muted hover:text-brand"
                          >
                            {busyId === doc.document_id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              "↪"
                            )}
                          </button>
                        ) : null}
                      </>
                    ) : null}
                  </>
                )}
                {moveId === doc.document_id && onMove ? (
                  <select
                    className="ml-1 h-6 max-w-[180px] rounded border border-line bg-white text-xs"
                    defaultValue=""
                    onChange={(e) => {
                      if (e.target.value) {
                        onMove(doc.document_id, e.target.value);
                        setMoveId(null);
                      }
                    }}
                  >
                    <option value="">挪到…</option>
                    {(allProjectNames ?? []).map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                ) : null}
              </span>
            ))}
        </div>
      ))}
    </div>
  );
}

function ProjectCard({
  title,
  ledger,
  evidence,
  evidenceProject,
  badge,
  note,
  canEdit,
  busyId,
  previewLoadingId,
  allProjectNames,
  onPreview,
  onMove,
  onRename
}: {
  title: string;
  ledger: PerformanceLedger;
  evidence: Record<string, PerformanceEvidenceDoc[]>;
  evidenceProject: string;
  badge: { tone: "ok" | "warn"; icon: ReactNode; text: string };
  note?: string;
  canEdit: boolean;
  busyId: number | string | null;
  previewLoadingId: number | null;
  allProjectNames: string[];
  onPreview: (doc: PerformanceEvidenceDoc) => void;
  onMove: (docId: number, target: string) => void;
  onRename: (docId: number, title: string) => void;
}) {
  return (
    <div
      className={[
        "rounded-lg border bg-white px-3 py-2",
        badge.tone === "warn" ? "border-amber-200" : "border-line"
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">{title}</p>
          <p className="text-xs text-muted">
            {ledger.year} · {ledger.amount} · 项目经理 {ledger.manager || "—"}
          </p>
        </div>
        <span
          className={[
            "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs",
            badge.tone === "ok" ? "bg-green-50 text-ok" : "bg-amber-50 text-amber-700"
          ].join(" ")}
        >
          {badge.icon}
          {badge.text}
        </span>
      </div>
      {note ? <p className="mt-1 text-xs text-amber-700">{note}</p> : null}
      <Bundle
        evidence={evidence}
        evidenceProject={evidenceProject}
        canEdit={canEdit}
        busyId={busyId}
        previewLoadingId={previewLoadingId}
        allProjectNames={allProjectNames}
        onPreview={onPreview}
        onMove={onMove}
        onRename={onRename}
      />
    </div>
  );
}

function ClaimCard({
  group,
  ledgerOptions,
  canEdit,
  busy,
  previewLoadingId,
  onPreview,
  onClaim
}: {
  group: PerformanceArchive["evidence_only"][number];
  ledgerOptions: PerformanceLedger[];
  canEdit: boolean;
  busy: boolean;
  previewLoadingId: number | null;
  onPreview: (doc: PerformanceEvidenceDoc) => void;
  onClaim: (target: string) => void;
}) {
  const [target, setTarget] = useState("");
  return (
    <div className="rounded-lg border border-amber-200 bg-white px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">{group.evidence_project}</p>
          <p className="text-xs text-amber-700">
            这堆证明对不上台账，请认领到正确的业绩项目
            {group.best_guess
              ? `（机器猜：${group.best_guess.slice(0, 22)}）`
              : ""}
          </p>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
          <ImageIcon className="h-3.5 w-3.5" />
          待认领 {group.total} 张
        </span>
      </div>

      <Bundle
        evidence={group.evidence}
        evidenceProject={group.evidence_project}
        canEdit={false}
        busyId={null}
        previewLoadingId={previewLoadingId}
        onPreview={onPreview}
      />

      {canEdit ? (
        <div className="mt-2 flex items-center gap-2">
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="h-8 min-w-0 flex-1 rounded-md border border-line bg-field px-2 text-xs text-ink"
          >
            <option value="">认领到哪个业绩台账…</option>
            {group.best_guess ? (
              <option value={group.best_guess}>★ 机器猜：{group.best_guess}</option>
            ) : null}
            {ledgerOptions.map((l) => (
              <option key={l.document_id} value={l.name}>
                {l.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!target || busy}
            onClick={() => onClaim(target)}
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md bg-brand px-3 text-xs font-semibold text-white hover:bg-blue-700 disabled:bg-blue-300"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            认领
          </button>
        </div>
      ) : null}
    </div>
  );
}
