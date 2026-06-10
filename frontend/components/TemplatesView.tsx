"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Database,
  FileStack,
  FolderOpen,
  Loader2,
  LogOut,
  Pencil,
  Plus,
  Trash2,
  UploadCloud,
  Users
} from "lucide-react";
import {
  deleteTemplate,
  listTemplates,
  logout as logoutRequest,
  updateTemplate,
  uploadTemplate
} from "@/lib/api";
import { clearSession, getStoredSession } from "@/lib/auth";
import { NavLinkButton } from "@/components/NavLinkButton";
import type { TemplateSummary } from "@/lib/types";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function TemplatesView() {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [projectType, setProjectType] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [envelopeType, setEnvelopeType] = useState("");
  const [region, setRegion] = useState("");
  const [projectYear, setProjectYear] = useState("");
  const [tags, setTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const session = getStoredSession();
    setIsAdmin(session?.role === "admin");
  }, []);

  async function handleLogout() {
    try {
      await logoutRequest();
    } catch {
      // Local logout should still proceed if the token has already expired.
    }
    clearSession();
    window.location.replace("/login");
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listTemplates();
      setTemplates(response.templates);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleUpload() {
    if (!file || !name.trim()) return;
    setUploading(true);
    setError(null);
    try {
      await uploadTemplate(file, name.trim(), {
        projectType: projectType.trim() || undefined,
        specialty: specialty.trim() || undefined,
        envelopeType: envelopeType.trim() || undefined,
        region: region.trim() || undefined,
        projectYear: projectYear ? Number(projectYear) : undefined,
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean)
      });
      setFile(null);
      setName("");
      setProjectType("");
      setSpecialty("");
      setEnvelopeType("");
      setRegion("");
      setProjectYear("");
      setTags("");
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch (uploadError) {
      setError(errorMessage(uploadError));
    } finally {
      setUploading(false);
    }
  }

  async function handleRename(template: TemplateSummary) {
    const next = window.prompt("重命名模板", template.name);
    if (!next || next.trim() === template.name) return;
    setError(null);
    try {
      await updateTemplate(template.id, { name: next.trim() });
      await load();
    } catch (renameError) {
      setError(errorMessage(renameError));
    }
  }

  async function handleDelete(template: TemplateSummary) {
    if (!window.confirm(`确认删除模板「${template.name}」？`)) return;
    setError(null);
    try {
      await deleteTemplate(template.id);
      setTemplates((current) => current.filter((item) => item.id !== template.id));
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    }
  }

  return (
    <main className="min-h-screen bg-field">
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6">
          <div className="flex items-center gap-3">
            <NavLinkButton href="/" icon={ArrowLeft}>
              返回主页
            </NavLinkButton>
            <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
              <FileStack className="h-5 w-5" />
              投标模板库
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <NavLinkButton href="/projects" icon={FolderOpen}>
              历史项目
            </NavLinkButton>
            <NavLinkButton href="/knowledge" icon={Database}>
              知识库
            </NavLinkButton>
            {isAdmin ? (
              <NavLinkButton href="/admin/users" icon={Users}>
                账号管理
              </NavLinkButton>
            ) : null}
            <NavLinkButton href="/" icon={Plus} variant="primary">
              新建项目
            </NavLinkButton>
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
            >
              <LogOut className="h-4 w-4" />
              退出
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-4 py-6 lg:px-6">
        {error ? (
          <div className="mb-4 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {isAdmin ? (
          <section className="mb-6 rounded-lg border border-line bg-white p-4 shadow-panel">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink">
              <UploadCloud className="h-4 w-4 text-brand" />
              上传历史投标文件作为模板（PDF）
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                className="text-sm text-ink"
              />
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="模板名称"
                className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
              />
              <input
                value={projectType}
                onChange={(event) => setProjectType(event.target.value)}
                placeholder="项目类型（如 公路工程）"
                className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
              />
              <input
                value={specialty}
                onChange={(event) => setSpecialty(event.target.value)}
                placeholder="专业（如 道路）"
                className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
              />
              <input
                value={envelopeType}
                onChange={(event) => setEnvelopeType(event.target.value)}
                placeholder="信封类型（如 第一信封）"
                className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
              />
              <input
                value={region}
                onChange={(event) => setRegion(event.target.value)}
                placeholder="地区（如 安徽）"
                className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
              />
              <input
                value={projectYear}
                onChange={(event) => setProjectYear(event.target.value)}
                placeholder="年份（如 2025）"
                className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
              />
              <input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="标签（逗号分隔）"
                className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
              />
            </div>
            <button
              type="button"
              onClick={() => void handleUpload()}
              disabled={uploading || !file || !name.trim()}
              className="mt-3 inline-flex h-9 items-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UploadCloud className="h-4 w-4" />
              )}
              解析并保存模板
            </button>
          </section>
        ) : (
          <p className="mb-4 text-sm text-muted">
            模板由管理员维护，下表可供创建项目时选择。
          </p>
        )}

        {templates.length === 0 && !loading ? (
          <div className="rounded-lg border border-dashed border-line bg-white px-6 py-12 text-center text-sm text-muted">
            暂无模板。
          </div>
        ) : null}

        <div className="space-y-3">
          {templates.map((template) => (
            <div
              key={template.id}
              className="flex flex-col gap-2 rounded-lg border border-line bg-white p-4 shadow-panel sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-ink">
                  {template.name}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  {template.project_type ? <span>类型：{template.project_type}</span> : null}
                  {template.specialty ? <span>专业：{template.specialty}</span> : null}
                  {template.envelope_type ? <span>{template.envelope_type}</span> : null}
                  {template.region ? <span>{template.region}</span> : null}
                  {template.project_year ? <span>{template.project_year}年</span> : null}
                  {template.page_count ? <span>{template.page_count}页</span> : null}
                </div>
                {template.tags?.length ? (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {template.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-brand"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              {isAdmin ? (
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleRename(template)}
                    className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
                  >
                    <Pencil className="h-4 w-4" />
                    重命名
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(template)}
                    className="inline-flex h-9 items-center gap-2 rounded-md border border-orange-200 bg-white px-3 text-sm font-medium text-danger hover:bg-orange-50"
                  >
                    <Trash2 className="h-4 w-4" />
                    删除
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
