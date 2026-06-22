"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  ImageIcon,
  Loader2,
  Pencil,
  X
} from "lucide-react";

import {
  getCompanyCertArchive,
  getKnowledgeDocumentPreview,
  getPersonCertArchive,
  reassignPersonCert,
  renameCert,
  retypeCompanyCert
} from "@/lib/api";
import { getStoredSession } from "@/lib/auth";
import type {
  CertDoc,
  CompanyCertArchive,
  PersonArchive,
  PersonArchiveEntry
} from "@/lib/types";

type Tab = "person" | "company";

const COMPANY_TYPE_OPTIONS = [
  "营业执照",
  "资质证书",
  "安全生产许可证",
  "开户许可证",
  "体系证书",
  "信用证书",
  "专利证书",
  "工法证书",
  "荣誉证书",
  "施工劳务资质证书"
];

export function CertArchivePanel() {
  const session = getStoredSession();
  const canEdit = session?.role === "admin";

  const [tab, setTab] = useState<Tab>("person");
  const [person, setPerson] = useState<PersonArchive | null>(null);
  const [company, setCompany] = useState<CompanyCertArchive | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | string | null>(null);

  // 预览
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewName, setPreviewName] = useState("");
  const [previewLoadingId, setPreviewLoadingId] = useState<number | null>(null);
  // 改名
  const [editId, setEditId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, c] = await Promise.all([
        getPersonCertArchive(),
        getCompanyCertArchive()
      ]);
      setPerson(p);
      setCompany(c);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "证件档案加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function preview(doc: CertDoc) {
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

  async function doRename(docId: number, title: string) {
    setBusyId(docId);
    try {
      await renameCert(docId, title);
      setEditId(null);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "改名失败");
    } finally {
      setBusyId(null);
    }
  }

  async function movePerson(key: string | number, docIds: number[], target: string) {
    if (!target.trim() || !docIds.length) return;
    setBusyId(key);
    try {
      await reassignPersonCert(docIds, target.trim());
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "改归属失败");
    } finally {
      setBusyId(null);
    }
  }

  async function retype(docIds: number[], target: string) {
    if (!target.trim() || !docIds.length) return;
    setBusyId(`retype-${docIds[0]}`);
    try {
      await retypeCompanyCert(docIds, target.trim());
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "改类型失败");
    } finally {
      setBusyId(null);
    }
  }

  const certChip = (doc: CertDoc, label: string, extra?: ReactNode) => (
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
          <button type="button" title="保存" className="text-ok" onClick={() => doRename(doc.document_id, editText)}>
            {busyId === doc.document_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          </button>
          <button type="button" title="取消" onClick={() => setEditId(null)}>
            <X className="h-3.5 w-3.5 text-muted" />
          </button>
        </>
      ) : (
        <>
          <button type="button" className="inline-flex items-center gap-1 hover:text-brand" title="查看原图" onClick={() => preview(doc)}>
            {previewLoadingId === doc.document_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <ImageIcon className="h-3 w-3" />}
            {label}
          </button>
          {canEdit ? (
            <button
              type="button"
              title="改名"
              className="text-muted hover:text-ink"
              onClick={() => {
                setEditId(doc.document_id);
                setEditText(label);
              }}
            >
              <Pencil className="h-3 w-3" />
            </button>
          ) : null}
          {extra}
        </>
      )}
    </span>
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-line bg-white px-4 py-6 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin" />
        正在加载证件档案…
      </div>
    );
  }

  return (
    <section className="space-y-3">
      {/* 页签 */}
      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={() => setTab("person")}
          className={["rounded-full border px-3 py-1 text-xs", tab === "person" ? "border-brand bg-blue-50 font-medium text-brand" : "border-line bg-field text-muted hover:text-ink"].join(" ")}
        >
          人员证件 {person ? `${person.stats.person_count}人` : ""}
        </button>
        <button
          type="button"
          onClick={() => setTab("company")}
          className={["rounded-full border px-3 py-1 text-xs", tab === "company" ? "border-brand bg-blue-50 font-medium text-brand" : "border-line bg-field text-muted hover:text-ink"].join(" ")}
        >
          公司证件 {company ? `${company.stats.cert_total}张` : ""}
        </button>
      </div>

      {error ? (
        <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-danger">{error}</div>
      ) : null}

      {tab === "person" && person ? (
        <PersonView
          data={person}
          canEdit={canEdit}
          busyId={busyId}
          certChip={certChip}
          onMove={movePerson}
        />
      ) : null}

      {tab === "company" && company ? (
        <div className="space-y-2">
          <p className="rounded-lg border border-line bg-white p-3 text-xs text-muted">
            按证件类型归类，共 <b className="text-ink">{company.stats.cert_total}</b> 张 /{" "}
            <b className="text-ink">{company.stats.type_count}</b> 类。
            <span className="text-amber-700">营业执照的正本/副本、多页都保留，不当重复删。</span>
          </p>
          {company.groups.map((g) => (
            <details key={g.cert_type} className="rounded-lg border border-line bg-white px-3 py-2">
              <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-ink">
                {g.cert_type}
                <span className="rounded-full bg-field px-2 py-0.5 text-xs text-muted">{g.total} 张</span>
              </summary>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {g.docs.map((doc, i) =>
                  certChip(
                    doc,
                    `【公司】${g.cert_type}_${String(i + 1).padStart(2, "0")}`,
                    canEdit ? (
                      <select
                        className="ml-1 h-5 max-w-[120px] rounded border border-line bg-white text-xs"
                        defaultValue=""
                        title="改证件类型"
                        onChange={(e) => {
                          if (e.target.value) retype([doc.document_id], e.target.value);
                        }}
                      >
                        <option value="">改类型…</option>
                        {COMPANY_TYPE_OPTIONS.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    ) : undefined
                  )
                )}
              </div>
            </details>
          ))}
        </div>
      ) : null}

      {/* 预览灯箱 */}
      {previewUrl ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={() => setPreviewUrl(null)}>
          <div className="max-h-[90vh] max-w-3xl overflow-auto rounded-lg bg-white p-3" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="truncate text-xs font-medium text-ink">{previewName}</p>
              <button type="button" onClick={() => setPreviewUrl(null)} className="grid h-7 w-7 place-items-center rounded-md border border-line text-muted hover:bg-field">
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

function PersonView({
  data,
  canEdit,
  busyId,
  certChip,
  onMove
}: {
  data: PersonArchive;
  canEdit: boolean;
  busyId: number | string | null;
  certChip: (doc: CertDoc, label: string, extra?: ReactNode) => ReactNode;
  onMove: (key: string | number, docIds: number[], target: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const persons = data.persons.filter((p) =>
    search.trim() ? p.name.includes(search.trim()) : true
  );

  const personPicker = (key: string | number, docIds: number[], placeholder: string) =>
    canEdit ? (
      <select
        className="h-7 max-w-[160px] rounded border border-line bg-white text-xs"
        defaultValue=""
        onChange={(e) => {
          if (e.target.value) onMove(key, docIds, e.target.value);
        }}
      >
        <option value="">{placeholder}</option>
        {data.person_names.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    ) : null;

  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-line bg-white p-3 text-xs text-muted">
        共 <b className="text-ink">{data.stats.person_count}</b> 人 /{" "}
        <b className="text-ink">{data.stats.cert_total}</b> 张证件
        {data.stats.unassigned ? (
          <>
            {" · "}
            <b className="text-amber-700">{data.stats.unassigned}</b> 张没主人待认领
          </>
        ) : null}
        <span className="text-amber-700"> · 身份证正反面、多页都保留，不当重复。</span>
      </div>

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="搜人名"
        className="h-8 w-full rounded-md border border-line bg-field px-3 text-xs text-ink"
      />

      {/* 未认领 */}
      {data.unassigned.length ? (
        <div className="rounded-lg border border-amber-200 bg-white px-3 py-2">
          <p className="mb-2 text-sm font-medium text-amber-700">
            待认领 · {data.unassigned.length} 张（没标人名，请认领到对应人员）
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.unassigned.map((doc) =>
              certChip(
                doc,
                doc.cert_type || "证件",
                personPicker(doc.document_id, [doc.document_id], "认领给…")
              )
            )}
          </div>
        </div>
      ) : null}

      {/* 人员卡(折叠) */}
      {persons.map((p: PersonArchiveEntry) => {
        const open = expanded === p.name;
        const allDocIds = Object.values(p.certs).flat().map((d) => d.document_id);
        return (
          <div key={p.name} className="rounded-lg border border-line bg-white px-3 py-2">
            <button
              type="button"
              className="flex w-full items-center gap-2 text-left"
              onClick={() => setExpanded(open ? null : p.name)}
            >
              {open ? <ChevronDown className="h-4 w-4 text-muted" /> : <ChevronRight className="h-4 w-4 text-muted" />}
              <span className="text-sm font-medium text-ink">{p.name}</span>
              <span className="flex flex-wrap gap-1">
                {Object.entries(p.types).map(([t, n]) => (
                  <span key={t} className="rounded-full bg-field px-2 py-0.5 text-xs text-muted">
                    {t}×{n}
                  </span>
                ))}
              </span>
              {busyId === p.name ? <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-muted" /> : null}
            </button>

            {open ? (
              <div className="mt-2 space-y-1.5 border-t border-line pt-2">
                {Object.entries(p.certs).map(([type, docs]) => (
                  <div key={type} className="flex flex-wrap items-center gap-1.5">
                    <span className="shrink-0 text-xs font-medium text-muted">{type}</span>
                    {docs.map((doc, i) =>
                      certChip(
                        doc,
                        `【人员·${p.name}】${type}_${String(i + 1).padStart(2, "0")}`,
                        personPicker(doc.document_id, [doc.document_id], "改归属…")
                      )
                    )}
                  </div>
                ))}
                {canEdit ? (
                  <div className="flex items-center gap-2 pt-1">
                    <span className="text-xs text-muted">把此人全部证件并入：</span>
                    {personPicker(p.name, allDocIds, "并入另一人…")}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
