"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getCurrentUser } from "@/lib/api";
import {
  AUTH_STORAGE_KEY,
  clearSession,
  getStoredSession,
  storeSession
} from "@/lib/auth";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false);
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function verifySession() {
      const redirectToLogin = () => {
        const next = `${window.location.pathname}${window.location.search}`;
        window.location.replace(`/login?next=${encodeURIComponent(next)}`);
      };

      const session = getStoredSession();
      if (!session) {
        redirectToLogin();
        return;
      }

      try {
        const me = await getCurrentUser();
        const storage = window.localStorage.getItem(AUTH_STORAGE_KEY)
          ? "local"
          : "session";
        storeSession(
          {
            ...session,
            username: me.user.username,
            displayName: me.user.display_name,
            role: me.user.role,
            canViewKnowledge: me.user.can_view_knowledge,
            canEditKnowledge: me.user.can_edit_knowledge
          },
          storage
        );
        if (!cancelled) {
          setAllowed(true);
          setChecked(true);
        }
      } catch {
        clearSession();
        if (!cancelled) {
          redirectToLogin();
        }
      }
    }

    void verifySession();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!checked || !allowed) {
    return (
      <main className="grid min-h-screen place-items-center bg-field p-4">
        <div className="flex items-center gap-3 rounded-lg border border-line bg-panel px-4 py-3 text-sm font-medium text-muted shadow-panel">
          <Loader2 className="h-4 w-4 animate-spin text-brand" />
          正在进入工作台
        </div>
      </main>
    );
  }

  return <>{children}</>;
}
