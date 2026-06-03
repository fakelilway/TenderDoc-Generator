"use client";

import { ChangeEvent, DragEvent, FormEvent, useRef, useState } from "react";
import { FileText, Loader2, Play, UploadCloud, X } from "lucide-react";

export function UploadPanel({
  projectName,
  file,
  busy,
  onProjectNameChange,
  onFileChange,
  onSubmit
}: {
  projectName: string;
  file: File | null;
  busy: boolean;
  onProjectNameChange: (value: string) => void;
  onFileChange: (file: File | null) => void;
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
    <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
      <div className="mb-4 flex items-center gap-2">
        <UploadCloud className="h-4 w-4 text-brand" />
        <h2 className="text-sm font-semibold text-ink">招标文件</h2>
      </div>

      <form className="space-y-4" onSubmit={submit}>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-muted">项目名称</span>
          <input
            value={projectName}
            onChange={(event) => onProjectNameChange(event.target.value)}
            className="h-10 w-full rounded-md border border-line bg-field px-3 text-sm text-ink"
            placeholder="项目名称"
          />
        </label>

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
            "flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed px-4 py-5 text-center transition",
            dragging
              ? "border-brand bg-blue-50"
              : "border-line bg-field hover:border-brand"
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
            <div className="flex w-full items-center gap-3 rounded-md border border-line bg-white px-3 py-3 text-left">
              <FileText className="h-5 w-5 shrink-0 text-brand" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{file.name}</p>
                <p className="text-xs text-muted">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
              <button
                type="button"
                title="移除"
                className="grid h-8 w-8 place-items-center rounded-md border border-line text-muted hover:bg-field"
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
              <UploadCloud className="mb-3 h-8 w-8 text-muted" />
              <p className="text-sm font-medium text-ink">PDF / DOCX / TXT</p>
            </>
          )}
        </div>

        <button
          type="submit"
          disabled={busy || !file || !projectName.trim()}
          className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
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
