"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ClipboardList, Trash2, UploadCloud } from "lucide-react";

import {
  deleteProjectBOQ,
  getProjectBOQ,
  uploadProjectBOQ,
  type ProjectBOQResponse
} from "@/lib/api";

// 工程量清单(另册)上传:清单常是另册、不在招标正文里。上传后抽全文存起来,生成技术卷时按真实
// 分部分项占比定详略(占比高的写厚、占比小的一笔带过)、把真实工程量喂给对应施工方案。
export function ProjectBOQPanel({ projectId }: { projectId: number }) {
  const [info, setInfo] = useState<ProjectBOQResponse | null>(null);
  const [uploaded, setUploaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getProjectBOQ(projectId);
      setUploaded(Boolean(res.uploaded));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleFile = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) {
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const res = await uploadProjectBOQ(projectId, files[0]);
        setInfo(res);
        setUploaded((res.chars ?? 0) > 0);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
        if (inputRef.current) {
          inputRef.current.value = "";
        }
      }
    },
    [projectId]
  );

  const handleDelete = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteProjectBOQ(projectId);
      setInfo(null);
      setUploaded(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-[#ff9500]/12 text-[#c2650a]">
            <ClipboardList className="h-4 w-4" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[#1d1d1f]">工程量清单(另册)</h2>
            <p className="text-[11px] text-[#8e8e93]">
              清单常是另册、不在招标正文里。传上来,技术卷就按真实分部分项占比定详略、引用真实工程量
            </p>
          </div>
        </div>
        {uploaded ? (
          <span className="shrink-0 rounded-full bg-[#34c759]/12 px-2.5 py-1 text-xs text-[#1f9d4d]">
            已上传
          </span>
        ) : (
          <span className="shrink-0 rounded-full bg-black/[0.05] px-2.5 py-1 text-xs text-[#6e6e73]">
            未上传
          </span>
        )}
      </div>

      <label
        className={[
          "mt-3 flex cursor-pointer items-center justify-center gap-2 rounded-[18px] border border-dashed px-4 py-4 text-sm transition",
          busy
            ? "cursor-progress border-black/[0.08] bg-black/[0.02] text-[#8e8e93]"
            : "border-[#ff9500]/30 bg-[#ff9500]/[0.06] text-[#c2650a] hover:bg-[#ff9500]/[0.1]"
        ].join(" ")}
      >
        <UploadCloud className="h-4 w-4" />
        {busy ? "抽取并解析占比中(约 30 秒)…" : "上传工程量清单(PDF / Word)"}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.doc,.docx,.txt"
          className="hidden"
          disabled={busy}
          onChange={(event) => void handleFile(event.target.files)}
        />
      </label>

      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}

      {info?.warning ? (
        <p className="mt-2 rounded-[12px] bg-[#ff9500]/[0.08] px-3 py-2 text-[11px] text-[#c2650a]">
          {info.warning}
        </p>
      ) : null}

      {info?.categories?.length ? (
        <div className="mt-3">
          <p className="text-[11px] text-[#8e8e93]">
            已解析 {info.categories.length} 个分部分项
            {info.dominant?.length ? (
              <span>
                {" "}
                · 主导:<b className="text-[#1d1d1f]">{info.dominant.join("、")}</b>
              </span>
            ) : null}
          </p>
          <div className="mt-1.5 space-y-1">
            {info.categories.map((c) => (
              <div
                key={c.name}
                className="flex items-center gap-2 rounded-[12px] border border-black/[0.06] bg-white/56 px-3 py-1.5"
              >
                <span className="w-28 shrink-0 truncate text-xs font-medium text-[#1d1d1f]">
                  {c.name}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-black/[0.06]">
                  <div
                    className="h-full rounded-full bg-[#ff9500]"
                    style={{ width: `${Math.min(100, Math.max(2, c.share_pct))}%` }}
                  />
                </div>
                <span className="w-10 shrink-0 text-right text-xs text-[#6e6e73]">
                  {c.share_pct}%
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {uploaded ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void handleDelete()}
          className="mt-2 inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] text-[#8e8e93] transition hover:bg-danger/10 hover:text-danger disabled:opacity-40"
        >
          <Trash2 className="h-3.5 w-3.5" /> 删除已上传清单
        </button>
      ) : null}
    </section>
  );
}
