"use client";

import { ChangeEvent, DragEvent, FormEvent, useRef, useState } from "react";
import { FileText, Loader2, Play, UploadCloud, X } from "lucide-react";
import type { TemplateSummary } from "@/lib/types";

export function UploadPanel({
  projectName,
  file,
  busy,
  templates = [],
  selectedTemplateId = null,
  recommendedTemplateId = null,
  onProjectNameChange,
  onFileChange,
  onTemplateChange,
  onSubmit
}: {
  projectName: string;
  file: File | null;
  busy: boolean;
  templates?: TemplateSummary[];
  selectedTemplateId?: number | null;
  recommendedTemplateId?: number | null;
  onProjectNameChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
  onTemplateChange?: (templateId: number | null) => void;
  onSubmit: () => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    onFileChange(selected);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    onFileChange(event.dataTransfer.files?.[0] ?? null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="mb-4 flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-[#007aff]/10 text-[#007aff]">
          <UploadCloud className="h-4 w-4" />
        </span>
        <h2 className="text-sm font-semibold text-[#1d1d1f]">招标文件</h2>
      </div>

      <form className="space-y-4" onSubmit={submit}>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted">项目名称</span>
          <input
            value={projectName}
            onChange={(event) => onProjectNameChange(event.target.value)}
            className="h-11 w-full rounded-[16px] border border-black/[0.08] bg-white/68 px-3.5 text-sm text-[#1d1d1f] shadow-[inset_0_1px_0_rgba(255,255,255,0.85)]"
            placeholder="项目名称"
          />
        </label>

        {templates.length > 0 && onTemplateChange ? (
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">
              公司风格案例{recommendedTemplateId != null ? "（有推荐，不自动套用）" : "（可选）"}
            </span>
            <select
              value={selectedTemplateId ?? ""}
              onChange={(event) =>
                onTemplateChange(
                  event.target.value ? Number(event.target.value) : null
                )
              }
              className="h-11 w-full rounded-[16px] border border-black/[0.08] bg-white/68 px-3.5 text-sm text-[#1d1d1f] shadow-[inset_0_1px_0_rgba(255,255,255,0.85)]"
            >
              <option value="">不使用案例（推荐，完全按招标文件格式）</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                  {template.id === recommendedTemplateId ? "（推荐）" : ""}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          className="hidden"
          onChange={chooseFile}
        />

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={[
            "flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-[22px] border border-dashed px-4 py-5 text-center transition",
            dragging
              ? "border-[#007aff] bg-[#007aff]/10"
              : "border-black/[0.1] bg-white/45 hover:border-[#007aff]/60 hover:bg-white/70"
          ].join(" ")}
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              inputRef.current?.click();
            }
          }}
        >
          {file ? (
            <div className="flex w-full items-center gap-3 rounded-[18px] border border-black/[0.08] bg-white/80 px-3 py-3 text-left shadow-sm">
              <FileText className="h-5 w-5 shrink-0 text-[#007aff]" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{file.name}</p>
                <p className="text-xs text-muted">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
              <button
                type="button"
                title="移除"
                className="grid h-8 w-8 place-items-center rounded-full border border-black/[0.08] text-muted hover:bg-black/[0.04]"
                onClick={(event) => {
                  event.stopPropagation();
                  onFileChange(null);
                  if (inputRef.current) {
                    inputRef.current.value = "";
                  }
                }}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <>
              <UploadCloud className="mb-3 h-8 w-8 text-[#8e8e93]" />
              <p className="text-sm font-medium text-ink">PDF / DOCX / TXT</p>
            </>
          )}
        </div>

        <button
          type="submit"
          disabled={busy || !file || !projectName.trim()}
          className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-full bg-[#007aff] px-4 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(0,122,255,0.22)] transition hover:bg-[#006ee6] disabled:cursor-not-allowed disabled:bg-[#b7d9ff] disabled:shadow-none"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          上传并启动
        </button>
      </form>
    </section>
  );
}
