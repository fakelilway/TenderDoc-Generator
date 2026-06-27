"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ClipboardList, Trash2, UploadCloud } from "lucide-react";

import {
  deleteProjectBOQ,
  getProjectBOQ,
  uploadProjectBOQ,
  type ProjectBOQResponse
} from "@/lib/api";

// 工程量清单(另册)上传:清单常是另册、不在招标正文里。面板始终显示(空白页也有)——
// 还没建项目时可先选清单文件,上传招标文件建好项目后自动上传并按真实分部分项占比定详略。
export function ProjectBOQPanel({ projectId }: { projectId: number | null }) {
  const [info, setInfo] = useState<ProjectBOQResponse | null>(null);
  const [uploaded, setUploaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    if (projectId == null) {
      return;
    }
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

  const doUpload = useCallback(async (pid: number, file: File) => {
    setBusy(true);
    setError(null);
    try {
      const res = await uploadProjectBOQ(pid, file);
      setInfo(res);
      setUploaded((res.chars ?? 0) > 0);
      setPendingFile(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  }, []);

  // 项目创建后(projectId 从无到有)自动上传之前选好的清单
  useEffect(() => {
    if (projectId != null && pendingFile && !busy) {
      void doUpload(projectId, pendingFile);
    }
    // 仅在 projectId 变化时触发(避免选文件即上传);doUpload/pendingFile 稳定不入依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const handleFile = useCallback(
    (files: FileList | null) => {
      if (!files?.length) {
        return;
      }
      const file = files[0];
      if (projectId == null) {
        setPendingFile(file); // 还没项目 → 先存着,建好后自动传
        setError(null);
      } else {
        void doUpload(projectId, file);
      }
    },
    [projectId, doUpload]
  );

  const handleDelete = useCallback(async () => {
    if (projectId == null) {
      setPendingFile(null);
      return;
    }
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

  const statusLabel = uploaded
    ? "已上传"
    : pendingFile
      ? "待建项目后上传"
      : "未上传";

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
        <span
          className={[
            "shrink-0 rounded-full px-2.5 py-1 text-xs",
            uploaded
              ? "bg-[#34c759]/12 text-[#1f9d4d]"
              : pendingFile
                ? "bg-[#ff9500]/12 text-[#c2650a]"
                : "bg-black/[0.05] text-[#6e6e73]"
          ].join(" ")}
        >
          {statusLabel}
        </span>
      </div>

      <label
        className={[
          "mt-3 flex cursor-pointer items-center justify-center gap-2 rounded-[18px] border border-dashed px-4 py-4 text-center text-sm transition",
          busy
            ? "cursor-progress border-black/[0.08] bg-black/[0.02] text-[#8e8e93]"
            : "border-[#ff9500]/30 bg-[#ff9500]/[0.06] text-[#c2650a] hover:bg-[#ff9500]/[0.1]"
        ].join(" ")}
      >
        <UploadCloud className="h-4 w-4 shrink-0" />
        {busy
          ? "抽取并解析占比中(约 30 秒)…"
          : pendingFile
            ? `已选:${pendingFile.name}`
            : "上传工程量清单(PDF / Word / Excel)"}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.doc,.docx,.txt,.xlsx,.xlsm,.xls"
          className="hidden"
          disabled={busy}
          onChange={(event) => handleFile(event.target.files)}
        />
      </label>

      {projectId == null ? (
        <p className="mt-2 rounded-[12px] bg-[#ff9500]/[0.08] px-3 py-2 text-[11px] text-[#c2650a]">
          {pendingFile
            ? "已选好清单——上传招标文件、项目建好后会自动上传并解析占比。"
            : "可先在此选择工程量清单;上传招标文件创建项目后会自动上传并解析占比。"}
        </p>
      ) : null}

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

      {uploaded || pendingFile ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void handleDelete()}
          className="mt-2 inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] text-[#8e8e93] transition hover:bg-danger/10 hover:text-danger disabled:opacity-40"
        >
          <Trash2 className="h-3.5 w-3.5" /> {pendingFile && !uploaded ? "取消选择" : "删除已上传清单"}
        </button>
      ) : null}
    </section>
  );
}
