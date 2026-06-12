"use client";

import { Database, FileStack, FolderOpen, Users } from "lucide-react";
import { AdminUsersPanel } from "@/components/AdminUsersPanel";
import { NavLinkButton } from "@/components/NavLinkButton";
import { ViewShell } from "@/components/ViewShell";
import { getStoredSession } from "@/lib/auth";

export function AdminUsersView() {
  const session = getStoredSession();
  const isAdmin = session?.role === "admin";
  const username = session?.displayName || session?.username || "";

  return (
    <ViewShell
      title="账号管理"
      icon={Users}
      actions={
        <>
          {username ? (
            <span className="inline-flex h-9 items-center rounded-md border border-line bg-white px-3 text-sm font-medium text-muted">
              {username}
            </span>
          ) : null}
          <NavLinkButton href="/projects" icon={FolderOpen}>
            历史项目
          </NavLinkButton>
          <NavLinkButton href="/knowledge" icon={Database}>
            知识库
          </NavLinkButton>
          {isAdmin ? (
            <NavLinkButton href="/templates" icon={FileStack}>
              风格库
            </NavLinkButton>
          ) : null}
        </>
      }
    >
      <AdminUsersPanel />
    </ViewShell>
  );
}
