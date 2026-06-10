"use client";

import {
  ArrowLeft,
  Database,
  FileStack,
  FolderOpen,
  LogOut,
  Plus,
  Users
} from "lucide-react";
import { AdminUsersPanel } from "@/components/AdminUsersPanel";
import { logout as logoutRequest } from "@/lib/api";
import { clearSession, getStoredSession } from "@/lib/auth";

export function AdminUsersView() {
  const session = getStoredSession();
  const isAdmin = session?.role === "admin";
  const username = session?.displayName || session?.username || "";

  async function handleLogout() {
    try {
      await logoutRequest();
    } catch {
      // Local logout should still proceed if the token has already expired.
    }
    clearSession();
    window.location.replace("/login");
  }

  return (
    <main className="min-h-screen bg-field">
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6">
          <div className="flex items-center gap-3">
            <a
              href="/"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
            >
              <ArrowLeft className="h-4 w-4" />
              返回主页
            </a>
            <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
              <Users className="h-5 w-5" />
              账号管理
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {username ? (
              <span className="inline-flex h-9 items-center rounded-md border border-line bg-white px-3 text-sm font-medium text-muted">
                {username}
              </span>
            ) : null}
            <a
              href="/projects"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
            >
              <FolderOpen className="h-4 w-4" />
              历史项目
            </a>
            <a
              href="/knowledge"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field"
            >
              <Database className="h-4 w-4" />
              知识库
            </a>
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

      <div className="mx-auto max-w-5xl px-4 py-6 lg:px-6">
        <AdminUsersPanel />
      </div>
    </main>
  );
}
