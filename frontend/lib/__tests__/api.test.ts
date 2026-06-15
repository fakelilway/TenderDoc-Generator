import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createProject, listProjects, login } from "../api";
import { AUTH_STORAGE_KEY, type AuthSession } from "../auth";

/**
 * These tests exercise the real `requestJson` plumbing inside lib/api.ts via a
 * few thin wrappers (login / listProjects / createProject). We mock the global
 * `fetch` and drive token injection through the real localStorage-backed
 * `getAccessToken` path (lib/auth.ts reads the `tenderdoc:session` key).
 */

function buildResponse(
  init: {
    ok?: boolean;
    status?: number;
    statusText?: string;
    json?: () => Promise<unknown>;
    text?: () => Promise<string>;
  } = {}
): Response {
  const status = init.status ?? 200;
  const ok = init.ok ?? (status >= 200 && status < 300);
  const json = init.json ?? (async () => ({}));
  const text = init.text ?? (async () => "");
  const response = {
    ok,
    status,
    statusText: init.statusText ?? "OK",
    json,
    text,
    // `requestJson` clones the response before reading text() in the catch
    // branch, so the clone needs its own independent body readers.
    clone() {
      return buildResponse(init);
    }
  };
  return response as unknown as Response;
}

function seedSession(accessToken: string) {
  const session: AuthSession = {
    accessToken,
    // Far future so getStoredSession() does not treat it as expired.
    expiresAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    username: "tester",
    displayName: "Tester",
    role: "admin",
    canViewKnowledge: true,
    canEditKnowledge: true,
    signedInAt: new Date().toISOString()
  };
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  fetchMock = vi.fn(async () => buildResponse({ json: async () => ({ ok: true }) }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("requestJson token injection", () => {
  it("injects Authorization: Bearer <token> when a session is stored", async () => {
    seedSession("tok-abc-123");

    await listProjects();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok-abc-123");
  });

  it("does not set an Authorization header when no session is stored", async () => {
    await listProjects();

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBeNull();
  });
});

describe("requestJson Content-Type handling", () => {
  it("sets Content-Type application/json for a plain JSON-string body", async () => {
    await login("user", "pass", "admin");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/login");
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(
      JSON.stringify({ username: "user", password: "pass", account_type: "admin" })
    );
  });

  it("does NOT set Content-Type for a FormData body", async () => {
    const file = new File(["dummy"], "tender.pdf", { type: "application/pdf" });

    await createProject("Proj", file);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/project/create");
    expect(init.body).toBeInstanceOf(FormData);
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBeNull();
  });
});

describe("requestJson error handling", () => {
  it("throws an Error carrying the backend `detail` message", async () => {
    fetchMock.mockResolvedValueOnce(
      buildResponse({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: async () => ({ detail: "用户名或密码错误" })
      })
    );

    await expect(login("user", "wrong", "admin")).rejects.toThrowError(
      "用户名或密码错误"
    );
  });

  it("falls back to the Chinese 500 message when there is no detail and an empty body", async () => {
    fetchMock.mockResolvedValueOnce(
      buildResponse({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => {
          throw new Error("not json");
        },
        text: async () => ""
      })
    );

    await expect(listProjects()).rejects.toThrowError(
      "后端请求中断或返回异常。任务可能仍在后台继续，请稍后刷新状态；如果状态变为失败，请查看页面保留的错误信息。"
    );
  });
});
