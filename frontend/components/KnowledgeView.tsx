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
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { NavLinkButton } from "@/components/NavLinkButton";
import { logout as logoutRequest } from "@/lib/api";
import { clearSession, getStoredSession } from "@/lib/auth";

export function KnowledgeView() {
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
            <NavLinkButton href="/" icon={ArrowLeft}>
              返回主页
            </NavLinkButton>
            <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
              <Database className="h-5 w-5" />
              知识库
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {username ? (
              <span className="inline-flex h-9 items-center rounded-md border border-line bg-white px-3 text-sm font-medium text-muted">
                {username}
              </span>
            ) : null}
            <NavLinkButton href="/projects" icon={FolderOpen}>
              历史项目
            </NavLinkButton>
            {isAdmin ? (
              <>
                <NavLinkButton href="/templates" icon={FileStack}>
                  模板库
                </NavLinkButton>
                <NavLinkButton href="/admin/users" icon={Users}>
                  账号管理
                </NavLinkButton>
              </>
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
        <KnowledgePanel />
      </div>
    </main>
  );
}
