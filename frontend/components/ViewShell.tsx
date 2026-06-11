"use client";

import { ArrowLeft, LogOut, Plus } from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { NavLinkButton } from "@/components/NavLinkButton";
import { logout as logoutRequest } from "@/lib/api";
import { clearSession } from "@/lib/auth";

type Props = {
  title: string;
  icon: ComponentType<{ className?: string }>;
  maxWidth?: "4xl" | "5xl";
  actions?: ReactNode;
  children: ReactNode;
};

export function ViewShell({
  title,
  icon: Icon,
  maxWidth = "5xl",
  actions,
  children
}: Props) {
  const widthClass = maxWidth === "4xl" ? "max-w-4xl" : "max-w-5xl";

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
        <div
          className={`mx-auto flex ${widthClass} flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6`}
        >
          <div className="flex shrink-0 items-center gap-3">
            <NavLinkButton href="/" icon={ArrowLeft}>
              返回主页
            </NavLinkButton>
            <h1 className="flex shrink-0 items-center gap-2 whitespace-nowrap text-lg font-semibold text-ink">
              <Icon className="h-5 w-5 shrink-0" />
              {title}
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {actions}
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

      <div className={`mx-auto ${widthClass} px-4 py-6 lg:px-6`}>{children}</div>
    </main>
  );
}
