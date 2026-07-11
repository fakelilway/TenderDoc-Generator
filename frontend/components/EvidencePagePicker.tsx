"use client";

import { useCallback, useState } from "react";
import { ChevronDown, ChevronRight, Eye, RotateCcw } from "lucide-react";

import {
  getEvidencePages,
  getKnowledgeDocumentPreview,
  saveEvidencePages
} from "@/lib/api";
import type { EvidencePageOption } from "@/lib/types";

// 业绩证明选页(员工意见7):默认规则每类取前几张(中标2/合同2/交工4),盖章页排在后面
// 会被截掉。点开这条业绩的全部扫描页,人工勾选;勾过以勾选为准、不设上限,
// "恢复默认"删除人工选页回到默认规则。展开才拉数据,不拖慢面板。

const TYPE_COLOR: Record<string, string> = {
  中标通知书: "bg-[#007aff]/12 text-[#0a6cff]",
  合同: "bg-[#af52de]/12 text-[#8e44ad]",
  交工验收: "bg-[#34c759]/12 text-[#1f9d4d]"
};

export function EvidencePagePicker({
  projectId,
  name
}: {
  projectId: number;
  name: string;
}) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [pages, setPages] = useState<EvidencePageOption[]>([]);
  // null=没人工选过(生成走默认规则,界面按默认预勾);列表=以勾选为准
  const [selected, setSelected] = useState<number[] | null>(null);
  const [defaultIds, setDefaultIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await getEvidencePages(projectId, name);
      setPages(res.pages);
      setSelected(res.selected);
      setDefaultIds(res.default_ids);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoaded(true);
    }
  }, [projectId, name]);

  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded) void load();
  };

  const effective = new Set(selected ?? defaultIds);

  const togglePage = async (docId: number) => {
    const next = new Set(effective);
    if (next.has(docId)) next.delete(docId);
    else next.add(docId);
    // 存页序(中标→合同→交工、按页码),勾选先后不影响出图顺序
    const ordered = pages
      .filter((p) => next.has(p.document_id))
      .map((p) => p.document_id);
    setSelected(ordered);
    setBusy(true);
    setError(null);
    try {
      await saveEvidencePages(projectId, name, ordered);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      void load(); // 失败回滚到服务端真值
    } finally {
      setBusy(false);
    }
  };

  const resetDefault = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveEvidencePages(projectId, name, null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const view = async (docId: number) => {
    try {
      const res = await getKnowledgeDocumentPreview(docId);
      if (res.preview_url) window.open(res.preview_url, "_blank");
    } catch {
      /* 看图失败不打断勾选 */
    }
  };

  return (
    <div className="ml-6 mt-1">
      <button
        type="button"
        onClick={toggleOpen}
        className="inline-flex items-center gap-1 text-[11px] text-[#6e6e73] transition hover:text-[#0a6cff]"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        证明材料选页
        {selected !== null ? (
          <span className="rounded bg-[#007aff]/12 px-1.5 py-0.5 text-[10px] text-[#0a6cff]">
            已手动选 {selected.length} 页
          </span>
        ) : (
          <span className="text-[10px] text-[#8e8e93]">（默认规则，盖章页在这里勾）</span>
        )}
      </button>

      {open ? (
        <div className="mt-1.5 rounded-[12px] border border-black/[0.06] bg-white/60 p-2">
          {error ? <p className="mb-1 text-[11px] text-danger">{error}</p> : null}
          {loaded && !error && pages.length === 0 ? (
            <p className="px-1 py-1 text-[11px] text-[#8e8e93]">
              证明库里没有这条业绩的扫描件，生成时不附图。
            </p>
          ) : null}
          {pages.length > 0 ? (
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <p className="text-[10px] text-[#8e8e93]">
                {selected === null
                  ? "当前按默认规则（中标2·合同2·交工4）预勾；勾/取消任意一页后以你的勾选为准，不再设上限。"
                  : `以勾选为准：${effective.size} / 共${pages.length}页会插进标书。`}
              </p>
              {selected !== null ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void resetDefault()}
                  className="inline-flex shrink-0 items-center gap-1 rounded-full border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[10px] text-[#6e6e73] transition hover:bg-white disabled:opacity-40"
                >
                  <RotateCcw className="h-2.5 w-2.5" /> 恢复默认
                </button>
              ) : null}
            </div>
          ) : null}
          <div className="max-h-[260px] space-y-1 overflow-auto">
            {pages.map((pg) => {
              const isSel = effective.has(pg.document_id);
              return (
                <div key={pg.document_id} className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void togglePage(pg.document_id)}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded-[8px] px-1.5 py-1 text-left transition hover:bg-black/[0.03] disabled:opacity-60"
                  >
                    <span
                      className={[
                        "grid h-3.5 w-3.5 shrink-0 place-items-center rounded border text-[9px] text-white",
                        isSel ? "border-[#34c759] bg-[#34c759]" : "border-black/20 bg-white"
                      ].join(" ")}
                    >
                      {isSel ? "✓" : ""}
                    </span>
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
                        TYPE_COLOR[pg.evidence_type] || "bg-black/[0.05] text-[#6e6e73]"
                      }`}
                    >
                      {pg.evidence_type}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[11px] text-[#1d1d1f]">
                      {pg.file_name || `第${pg.evidence_seq}页`}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void view(pg.document_id)}
                    className="inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] text-[#0a6cff] transition hover:bg-[#007aff]/10"
                  >
                    <Eye className="h-3 w-3" /> 看图
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
