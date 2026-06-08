"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Download,
  FileStack,
  FolderOpen,
  Loader2,
  LogOut,
  Plus,
  RefreshCw,
  Trash2
} from "lucide-react";
import { deleteProject, listProjects, logout as logoutRequest } from "@/lib/api";
import { clearSession, getStoredSession } from "@/lib/auth";
import type { ProjectSummary } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  uploading: "上传中",
  uploaded: "已上传",
  parsing: "解析中",
  parsed: "已解析",
  parsed_confirmed: "解析已确认",
  outline_ready: "大纲待确认",
  outline_confirmed: "大纲已确认",
  outline_review: "待确认大纲",
  processing: "处理中",
  generating: "生成中",
  generated: "已生成",
  reviewing: "审查中",
  human_review: "待确认",
  needs_revision: "待修正",
  approved: "已批准",
  finished: "已完成",
  failed: "失败",
  generation_failed: "生成失败"
};

const FINAL_STATUSES = new Set(["approved", "finished", "generated"]);
const FAILED_STATUSES = new Set(["failed", "generation_failed"]);

function statusTone(status: string) {
  if (FINAL_STATUSES.has(status)) return "bg-green-50 text-ok";
  if (FAILED_STATUSES.has(status)) return "bg-orange-50 text-danger";
  return "bg-blue-50 text-brand";
}

function formatDate(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function ProjectsView() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [username, setUsername] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const session = getStoredSession();
    setUsername(session?.displayName || session?.username || "");
    setIsAdmin(session?.role === "admin");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listProjects();
      setProjects(response.projects);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : String(loadError)
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const owners = useMemo(() => {
    const seen = new Map<number, string>();
    for (const project of projects) {
      if (project.owner_user_id != null && !seen.has(project.owner_user_id)) {
        seen.set(
          project.owner_user_id,
          project.owner_display_name ||
            project.owner_username ||
            `用户 ${project.owner_user_id}`
        );
      }
    }
    return Array.from(seen.entries());
  }, [projects]);

  const visibleProjects = useMemo(() => {
    if (!isAdmin || ownerFilter === "all") return projects;
    return projects.filter(
      (project) => String(project.owner_user_id) === ownerFilter
    );
  }, [projects, isAdmin, ownerFilter]);

  async function handleDelete(project: ProjectSummary) {
    const confirmed = window.confirm(
      `确认删除项目「${project.name}」？该操作不可恢复。`
    );
    if (!confirmed) return;
    setDeletingId(project.project_id);
    setError(null);
    try {
      await deleteProject(project.project_id);
      setProjects((current) =>
        current.filter((item) => item.project_id !== project.project_id)
      );
    } catch (deleteError) {
      setError(
        deleteError instanceof Error ? deleteError.message : String(deleteError)
      );
    } finally {
      setDeletingId(null);
    }
  }

  async function handleLogout() {
    try {
      await logoutRequest();
    } catch {
      // Local logout proceeds even if the token has already expired.
    }
    clearSession();
    window.location.replace("/login");
  }

  return (
    <main className="min-h-screen bg-field">
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-4xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6">
          <div className="flex items-center gap-3">
            <a
              href="/"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
            >
              <ArrowLeft className="h-4 w-4" />
              返回主页
            </a>
            <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
              <FolderOpen className="h-5 w-5" />
              历史项目
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {username ? (
              <span className="inline-flex h-9 items-center rounded-md border border-line bg-field px-3 text-sm font-medium text-muted">
                {username}
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field disabled:cursor-not-allowed disabled:text-muted"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              刷新
            </button>
            {isAdmin ? (
              <a
                href="/templates"
                className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
              >
                <FileStack className="h-4 w-4" />
                模板库
              </a>
            ) : null}
            <a
              href="/"
              className="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3 text-sm font-semibold text-white hover:bg-blue-700"
            >
              <Plus className="h-4 w-4" />
              新建项目
            </a>
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

      <div className="mx-auto max-w-4xl px-4 py-6 lg:px-6">
        {error ? (
          <div className="mb-4 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {isAdmin && owners.length > 0 ? (
          <div className="mb-4 flex items-center gap-2">
            <label className="text-sm text-muted">按用户筛选</label>
            <select
              value={ownerFilter}
              onChange={(event) => setOwnerFilter(event.target.value)}
              className="rounded-md border border-line bg-white px-2 py-1 text-sm text-ink"
            >
              <option value="all">全部用户</option>
              {owners.map(([id, label]) => (
                <option key={id} value={String(id)}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {visibleProjects.length === 0 && !loading ? (
          <div className="rounded-lg border border-dashed border-line bg-white px-6 py-12 text-center text-sm text-muted">
            暂无历史项目，点击右上角「新建项目」开始。
          </div>
        ) : null}

        <div className="space-y-3">
          {visibleProjects.map((project) => (
            <div
              key={project.project_id}
              className="flex flex-col gap-3 rounded-lg border border-line bg-white p-4 shadow-panel sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-ink">
                    {project.name}
                  </span>
                  {project.has_download ? (
                    <Download className="h-4 w-4 shrink-0 text-ok" />
                  ) : null}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span>#{project.project_id}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 ${statusTone(project.status)}`}
                  >
                    {STATUS_LABELS[project.status] ?? project.status}
                  </span>
                  <span>{formatDate(project.created_at)}</span>
                  {isAdmin && project.owner_user_id != null ? (
                    <span>
                      {project.owner_display_name ||
                        project.owner_username ||
                        `用户 ${project.owner_user_id}`}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <a
                  href={`/project/${project.project_id}`}
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-brand hover:border-brand hover:bg-blue-50"
                >
                  打开
                </a>
                <button
                  type="button"
                  onClick={() => void handleDelete(project)}
                  disabled={deletingId === project.project_id}
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-orange-200 bg-white px-3 text-sm font-medium text-danger hover:bg-orange-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deletingId === project.project_id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
