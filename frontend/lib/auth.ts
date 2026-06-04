export const AUTH_STORAGE_KEY = "tenderdoc:session";

export type AuthSession = {
  accessToken: string;
  expiresAt: string;
  username: string;
  displayName?: string | null;
  role: string;
  signedInAt: string;
};

export function getStoredSession(): AuthSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw =
    window.localStorage.getItem(AUTH_STORAGE_KEY) ??
    window.sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<AuthSession>;
    if (!parsed.username || !parsed.accessToken || !parsed.expiresAt) {
      return null;
    }
    if (new Date(parsed.expiresAt).getTime() <= Date.now()) {
      clearSession();
      return null;
    }
    return {
      accessToken: parsed.accessToken,
      expiresAt: parsed.expiresAt,
      username: parsed.username,
      displayName: parsed.displayName ?? null,
      role: parsed.role ?? "user",
      signedInAt: parsed.signedInAt ?? new Date().toISOString()
    };
  } catch {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
    return null;
  }
}

export function storeSession(
  session: AuthSession,
  storage: "local" | "session" = "local"
): void {
  const serialized = JSON.stringify(session);
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
  window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  if (storage === "local") {
    window.localStorage.setItem(AUTH_STORAGE_KEY, serialized);
  } else {
    window.sessionStorage.setItem(AUTH_STORAGE_KEY, serialized);
  }
}

export function clearSession() {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  }
}

export function getAccessToken(): string | null {
  return getStoredSession()?.accessToken ?? null;
}
