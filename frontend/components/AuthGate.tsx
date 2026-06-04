"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getCurrentUser } from "@/lib/api";
import { clearSession, getStoredSession } from "@/lib/auth";

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
        await getCurrentUser();
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
