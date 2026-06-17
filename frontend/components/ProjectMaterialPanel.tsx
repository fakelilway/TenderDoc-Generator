"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Trash2, UploadCloud } from "lucide-react";

import {
  deleteProjectMaterial,
  listProjectMaterials,
  uploadProjectMaterial
} from "@/lib/api";
import type { KnowledgeDocumentSummary } from "@/lib/types";

// M23 本项目专用技术材料库:上传同类施工组织设计 / 施工方案参考。project_id 隔离入库,
// 仅用于本项目技术卷生成的检索接地(grounding),不进全局库、不污染其它项目。
export function ProjectMaterialPanel({ projectId }: { projectId: number }) {
  const [items, setItems] = useState<KnowledgeDocumentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // ② 插入图:目标章节 + 说明
  const [imgSection, setImgSection] = useState("");
  const [imgCaption, setImgCaption] = useState("");
  const imgInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await listProjectMaterials(projectId);
      setItems(res.documents);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoaded(true);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleImage = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) {
        return;
      }
      setBusy(true);
      setError(null);
      try {
        for (const file of Array.from(files)) {
          await uploadProjectMaterial(projectId, file, {
            targetSection: imgSection.trim(),
            caption: imgCaption.trim()
          });
        }
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
        if (imgInputRef.current) {
          imgInputRef.current.value = "";
        }
      }
    },
    [projectId, refresh, imgSection, imgCaption]
  );

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) {
        return;
      }
      setBusy(true);
      setError(null);
      try {
        for (const file of Array.from(files)) {
          await uploadProjectMaterial(projectId, file);
        }
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
        if (inputRef.current) {
          inputRef.current.value = "";
        }
      }
    },
    [projectId, refresh]
  );

  const handleDelete = useCallback(
    async (documentId: number) => {
      setBusy(true);
      setError(null);
      try {
        await deleteProjectMaterial(projectId, documentId);
        await refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
      }
    },
    [projectId, refresh]
  );

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-[#34c759]/12 text-[#1f9d4d]">
            <FileText className="h-4 w-4" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[#1d1d1f]">本项目技术材料</h2>
            <p className="text-[11px] text-[#8e8e93]">
              上传同类施工组织设计 / 施工方案参考,仅用于本项目技术卷接地,不进全局库
            </p>
          </div>
        </div>
        <span className="shrink-0 rounded-full bg-black/[0.05] px-2.5 py-1 text-xs text-[#6e6e73]">
          {items.length} 份
        </span>
      </div>

      <label
        className={[
          "mt-3 flex cursor-pointer items-center justify-center gap-2 rounded-[18px] border border-dashed px-4 py-4 text-sm transition",
          busy
            ? "cursor-progress border-black/[0.08] bg-black/[0.02] text-[#8e8e93]"
            : "border-[#34c759]/30 bg-[#34c759]/[0.06] text-[#1f9d4d] hover:bg-[#34c759]/[0.1]"
        ].join(" ")}
      >
        <UploadCloud className="h-4 w-4" />
        {busy ? "上传并索引中…" : "选择文件上传(PDF / Word / 文本,可多选)"}
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.txt,.md"
          className="hidden"
          disabled={busy}
          onChange={(event) => void handleFiles(event.target.files)}
        />
      </label>

      <div className="mt-2 rounded-[16px] border border-[#007aff]/20 bg-[#007aff]/[0.04] p-3">
        <p className="text-[11px] font-medium text-[#007aff]">
          本项目插入图(航拍图 / 图纸 → 自动插到技术卷指定章节)
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            value={imgSection}
            onChange={(event) => setImgSection(event.target.value)}
            placeholder="插到哪一节(如:施工总平面布置;留空进末尾「本项目附图」)"
            className="flex-1 rounded-[12px] border border-black/[0.1] bg-white px-3 py-1.5 text-xs text-[#1d1d1f] placeholder:text-[#b0b0b5]"
          />
          <input
            value={imgCaption}
            onChange={(event) => setImgCaption(event.target.value)}
            placeholder="图说明(可选)"
            className="rounded-[12px] border border-black/[0.1] bg-white px-3 py-1.5 text-xs text-[#1d1d1f] placeholder:text-[#b0b0b5] sm:w-28"
          />
        </div>
        <label className="mt-2 flex cursor-pointer items-center justify-center gap-2 rounded-[12px] border border-dashed border-[#007aff]/30 bg-white/70 px-3 py-2 text-xs text-[#007aff] transition hover:bg-white">
          <UploadCloud className="h-3.5 w-3.5" />
          选择图片上传(JPG / PNG,可多选)
          <input
            ref={imgInputRef}
            type="file"
            multiple
            accept="image/*"
            className="hidden"
            disabled={busy}
            onChange={(event) => void handleImage(event.target.files)}
          />
        </label>
      </div>

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      <div className="mt-3 space-y-1.5">
        {loaded && items.length === 0 ? (
          <p className="rounded-[14px] border border-dashed border-black/[0.08] bg-white/54 px-3 py-3 text-center text-xs text-[#8e8e93]">
            还没有本项目材料。传一份同类施工组织设计,生成的技术卷会据此接地、少编。
          </p>
        ) : null}
        {items.map((doc) => {
          const notIndexed =
            doc.indexing_status && doc.indexing_status !== "indexed";
          return (
            <div
              key={doc.document_id}
              className="flex items-center justify-between gap-3 rounded-[14px] border border-black/[0.06] bg-white/56 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-[#1d1d1f]">
                  {doc.file_name}
                </p>
                <p className="text-[11px] text-[#8e8e93]">
                  {doc.chunk_count} 段已索引
                  {notIndexed ? (
                    <span className="text-[#d08700]">
                      {" "}
                      · 未提取到文字({doc.indexing_status})
                    </span>
                  ) : null}
                </p>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleDelete(doc.document_id)}
                className="shrink-0 rounded-full p-1.5 text-[#8e8e93] transition hover:bg-danger/10 hover:text-danger disabled:opacity-40"
                aria-label="删除材料"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
