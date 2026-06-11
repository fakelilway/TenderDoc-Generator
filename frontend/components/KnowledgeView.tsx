"use client";

import { Database, FileStack, FolderOpen, Users } from "lucide-react";
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { NavLinkButton } from "@/components/NavLinkButton";
import { ViewShell } from "@/components/ViewShell";
import { getStoredSession } from "@/lib/auth";

export function KnowledgeView() {
  const session = getStoredSession();
  const isAdmin = session?.role === "admin";
  const username = session?.displayName || session?.username || "";

  return (
    <ViewShell
      title="知识库"
      icon={Database}
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
        </>
      }
    >
      <KnowledgePanel />
    </ViewShell>
  );
}
