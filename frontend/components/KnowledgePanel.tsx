"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import {
  Check,
  Database,
  FileText,
  Layers3,
  Loader2,
  LockKeyhole,
  Pencil,
  Search,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import {
  deleteKnowledgeDocument,
  listKnowledgeDocuments,
  renameKnowledgeDocument,
  searchKnowledge,
  uploadKnowledge
} from "@/lib/api";
import { getStoredSession } from "@/lib/auth";
import type {
  KnowledgeDocumentSummary,
  KnowledgeSearchResult
} from "@/lib/types";

function metadataText(result: KnowledgeSearchResult) {
  const fileName = result.metadata.file_name;
  if (typeof fileName === "string" && fileName) {
    return fileName;
  }
  return result.document_id ? `Document ${result.document_id}` : "知识库片段";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function KnowledgePanel() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const session = getStoredSession();
  const canView = Boolean(session?.canViewKnowledge);
  const canEdit = Boolean(session?.canEditKnowledge);
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [projectYear, setProjectYear] = useState("");
  const [tagText, setTagText] = useState("");
  const [query, setQuery] = useState("施工组织设计 工期 质量 安全");
  const [results, setResults] = useState<KnowledgeSearchResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<string | null>(null);

  async function refreshDocuments() {
    if (!canView) {
      return;
    }
    setLoadingDocuments(true);
    try {
      const response = await listKnowledgeDocuments();
      setDocuments(response.documents);
    } catch (listError) {
      setError(listError instanceof Error ? listError.message : "知识库加载失败");
    } finally {
      setLoadingDocuments(false);
    }
  }

  useEffect(() => {
    void refreshDocuments();
  }, [canView]);

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setLastUpload(null);
    setError(null);
  }

  async function handleUpload() {
    if (!file || !canEdit) {
      return;
    }

    setBusy(true);
    setError(null);
    setLastUpload(null);
    try {
      const response = await uploadKnowledge(file, {
        documentType: documentType.trim() || undefined,
        specialty: specialty.trim() || undefined,
        projectYear: projectYear.trim() ? Number(projectYear) : null,
        tags: tagText
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean)
      });
      setLastUpload(`${file.name}：${response.chunk_ids.length} 个片段`);
      setFile(null);
      setDocumentType("");
      setSpecialty("");
      setProjectYear("");
      setTagText("");
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await refreshDocuments();
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "知识库上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSearch(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const value = query.trim();
    if (!value || !canView) {
      return;
    }

    setSearching(true);
    setError(null);
    try {
      const response = await searchKnowledge(value, 5);
      setResults(response.results);
    } catch (searchError) {
      setError(searchError instanceof Error ? searchError.message : "知识库检索失败");
    } finally {
      setSearching(false);
    }
  }

  function startEditing(document: KnowledgeDocumentSummary) {
    setEditingId(document.document_id);
    setEditingTitle(document.file_name);
    setError(null);
  }

  async function saveTitle(documentId: number) {
    const title = editingTitle.trim();
    if (!title) {
      setError("标题不能为空");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await renameKnowledgeDocument(documentId, title);
      setEditingId(null);
      setEditingTitle("");
      setResults([]);
      await refreshDocuments();
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "标题更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteDocument(document: KnowledgeDocumentSummary) {
    if (!window.confirm(`确认从知识库删除「${document.file_name}」？`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteKnowledgeDocument(document.document_id);
      setResults((current) =>
        current.filter((result) => result.document_id !== document.document_id)
      );
      await refreshDocuments();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "知识库删除失败");
    } finally {
      setBusy(false);
    }
  }

  const totalChunks = documents.reduce(
    (sum, document) => sum + document.chunk_count,
    0
  );

  if (!canView) {
    return (
      <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
        <div className="mb-4 flex items-center gap-2">
          <Database className="h-4 w-4 text-brand" />
          <h2 className="text-sm font-semibold text-ink">知识库</h2>
        </div>
        <div className="rounded-md border border-dashed border-line bg-field px-3 py-4 text-center">
          <LockKeyhole className="mx-auto mb-2 h-5 w-5 text-muted" />
          <p className="text-sm font-medium text-ink">暂无知识库权限</p>
          <p className="mt-1 text-xs leading-5 text-muted">
            需要管理员授权查看或编辑权限。
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-brand" />
          <h2 className="text-sm font-semibold text-ink">知识库</h2>
        </div>
        <span className="rounded-md border border-line bg-field px-2 py-1 text-xs font-medium text-muted">
          {documents.length} 文件 · {totalChunks} 片段
        </span>
      </div>

      <div className="space-y-4">
        {canEdit ? (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt"
              className="hidden"
              onChange={chooseFile}
            />

            {file ? (
              <div className="flex items-center gap-3 rounded-md border border-line bg-field px-3 py-3">
                <FileText className="h-4 w-4 shrink-0 text-brand" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{file.name}</p>
                  <p className="text-xs text-muted">
                    {(file.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                </div>
                <button
                  type="button"
                  title="移除"
                  className="grid h-8 w-8 place-items-center rounded-md border border-line text-muted hover:bg-white"
                  onClick={() => {
                    setFile(null);
                    if (fileInputRef.current) {
                      fileInputRef.current.value = "";
                    }
                  }}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="flex min-h-24 w-full flex-col items-center justify-center rounded-lg border border-dashed border-line bg-field px-3 py-4 text-center hover:border-brand"
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadCloud className="mb-2 h-6 w-6 text-muted" />
                <span className="text-sm font-medium text-ink">
                  上传历史标书 / 企业资料
                </span>
                <span className="mt-1 text-xs text-muted">PDF / DOCX / TXT</span>
              </button>
            )}

            <div className="grid grid-cols-2 gap-2">
              <input
                value={documentType}
                onChange={(event) => setDocumentType(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="资料类型"
              />
              <input
                value={specialty}
                onChange={(event) => setSpecialty(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="专业"
              />
              <input
                value={projectYear}
                onChange={(event) => setProjectYear(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="年份"
              />
              <input
                value={tagText}
                onChange={(event) => setTagText(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="标签，逗号分隔"
              />
            </div>

            <button
              type="button"
              disabled={!file || busy}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
              onClick={handleUpload}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UploadCloud className="h-4 w-4" />
              )}
              入库并向量化
            </button>
          </>
        ) : (
          <div className="rounded-md border border-line bg-field px-3 py-3 text-xs leading-5 text-muted">
            当前账号可查看和检索知识库，上传、删除和标题编辑需要管理员授权。
          </div>
        )}

        <form className="space-y-2" onSubmit={handleSearch}>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">
              检索测试
            </span>
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-10 min-w-0 flex-1 rounded-md border border-line bg-field px-3 text-sm text-ink"
                placeholder="输入标书章节、工法、资质关键词"
              />
              <button
                type="submit"
                disabled={searching || !query.trim()}
                title="检索"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-ink text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {searching ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
              </button>
            </div>
          </label>
        </form>

        {error ? (
          <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-xs leading-5 text-danger">
            {error}
          </div>
        ) : null}

        {lastUpload ? (
          <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs leading-5 text-ok">
            {lastUpload}
          </div>
        ) : null}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-muted">入库文档</p>
            {loadingDocuments ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted" />
            ) : null}
          </div>
          <div className="max-h-48 space-y-2 overflow-auto">
            {documents.length === 0 ? (
              <div className="rounded-md border border-dashed border-line bg-field px-3 py-4 text-center text-xs text-muted">
                暂无知识库文档
              </div>
            ) : (
              documents.slice(0, 8).map((document) => (
                <div
                  key={document.document_id}
                  className="rounded-md border border-line bg-white px-3 py-2"
                >
                  {editingId === document.document_id ? (
                    <div className="flex items-center gap-2">
                      <input
                        value={editingTitle}
                        onChange={(event) => setEditingTitle(event.target.value)}
                        className="h-8 min-w-0 flex-1 rounded-md border border-line bg-field px-2 text-xs text-ink"
                        autoFocus
                      />
                      <button
                        type="button"
                        title="保存标题"
                        disabled={busy}
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-ok text-white disabled:bg-green-300"
                        onClick={() => saveTitle(document.document_id)}
                      >
                        {busy ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                      </button>
                      <button
                        type="button"
                        title="取消"
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-line text-muted hover:bg-field"
                        onClick={() => setEditingId(null)}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-start gap-2">
                      <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-ink">
                          {document.file_name}
                        </p>
                        <p className="mt-1 text-xs text-muted">
                          {document.chunk_count} 片段 · {formatDate(document.created_at)}
                        </p>
                        {document.document_type || document.specialty || document.tags?.length ? (
                          <p className="mt-1 truncate text-xs text-muted">
                            {[document.document_type, document.specialty, ...(document.tags ?? [])]
                              .filter(Boolean)
                              .join(" / ")}
                          </p>
                        ) : null}
                      </div>
                      {canEdit ? (
                        <div className="flex shrink-0 gap-1">
                          <button
                            type="button"
                            title="编辑标题"
                            className="grid h-7 w-7 place-items-center rounded-md border border-line text-muted hover:bg-field"
                            onClick={() => startEditing(document)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            title="删除"
                            disabled={busy}
                            className="grid h-7 w-7 place-items-center rounded-md border border-line text-danger hover:bg-orange-50 disabled:cursor-not-allowed disabled:text-muted"
                            onClick={() => deleteDocument(document)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted">命中片段</p>
          <div className="max-h-80 space-y-2 overflow-auto">
            {results.length === 0 ? (
              <div className="rounded-md border border-dashed border-line bg-field px-3 py-4 text-center text-xs text-muted">
                等待检索
              </div>
            ) : (
              results.map((result) => (
                <div
                  key={result.chunk_id}
                  className="rounded-md border border-line bg-white px-3 py-2"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-medium text-ink">
                      {metadataText(result)}
                    </p>
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line bg-field px-1.5 py-0.5 text-xs text-muted">
                      <Layers3 className="h-3 w-3" />
                      {(result.score * 100).toFixed(0)}
                    </span>
                  </div>
                  <p className="line-clamp-4 text-xs leading-5 text-muted">
                    {result.content}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
