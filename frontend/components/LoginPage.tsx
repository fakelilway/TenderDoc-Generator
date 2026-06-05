"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Eye,
  EyeOff,
  FileCheck2,
  KeyRound,
  Loader2,
  LockKeyhole,
  LogIn,
  ShieldCheck,
  User,
  UserPlus
} from "lucide-react";
import { login, registerUser } from "@/lib/api";
import { getStoredSession, storeSession } from "@/lib/auth";
import type { LoginResponse } from "@/lib/types";

const DEFAULT_USERNAME = "admin";
const DEFAULT_PASSWORD = "tenderdoc";

type AccountType = "admin" | "user";
type AuthMode = "login" | "register";

function nextPathFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");
  if (next?.startsWith("/") && !next.startsWith("//")) {
    return next;
  }
  return "/";
}

export function LoginPage() {
  const [accountType, setAccountType] = useState<AccountType>("admin");
  const [mode, setMode] = useState<AuthMode>("login");
  const [username, setUsername] = useState(DEFAULT_USERNAME);
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRegistering = accountType === "user" && mode === "register";
  const canSubmit = useMemo(() => {
    if (busy || !username.trim() || !password) {
      return false;
    }
    if (!isRegistering) {
      return true;
    }
    return password.length >= 6 && password === confirmPassword && verificationCode.trim().length > 0;
  }, [busy, confirmPassword, isRegistering, password, username, verificationCode]);

  function persistLogin(result: LoginResponse) {
    storeSession(
      {
        accessToken: result.access_token,
        expiresAt: new Date(Date.now() + result.expires_in * 1000).toISOString(),
        username: result.user.username,
        displayName: result.user.display_name,
        role: result.user.role,
        canViewKnowledge: result.user.can_view_knowledge,
        canEditKnowledge: result.user.can_edit_knowledge,
        signedInAt: new Date().toISOString()
      },
      remember ? "local" : "session"
    );
    window.location.replace(nextPathFromLocation());
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) {
      if (isRegistering && password !== confirmPassword) {
        setError("两次密码不一致");
      }
      return;
    }

    setBusy(true);
    setError(null);

    try {
      if (isRegistering) {
        const result = await registerUser({
          username: username.trim(),
          password,
          display_name: displayName.trim() || null,
          verification_code: verificationCode.trim()
        });
        persistLogin(result);
        return;
      }

      const result = await login(username.trim(), password, accountType);
      persistLogin(result);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  function selectAccountType(nextType: AccountType) {
    setAccountType(nextType);
    setMode("login");
    setError(null);
    setPassword("");
    setConfirmPassword("");
    setVerificationCode("");
    if (nextType === "admin") {
      setUsername(DEFAULT_USERNAME);
    } else if (username === DEFAULT_USERNAME) {
      setUsername("");
    }
  }

  function fillDemoAccount() {
    setAccountType("admin");
    setMode("login");
    setUsername(DEFAULT_USERNAME);
    setPassword(DEFAULT_PASSWORD);
    setError(null);
  }

  useEffect(() => {
    if (getStoredSession()) {
      window.location.replace(nextPathFromLocation());
    }
  }, []);

  return (
    <main className="min-h-screen bg-[#eef2f6]">
      <div className="grid min-h-screen lg:grid-cols-[minmax(360px,0.92fr)_1.08fr]">
        <section className="flex min-h-[42vh] flex-col justify-between border-b border-line bg-[#172033] px-6 py-6 text-white lg:min-h-screen lg:border-b-0 lg:border-r lg:px-10">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-md bg-white text-brand">
              <FileCheck2 className="h-5 w-5" />
            </span>
            <div>
              <p className="text-sm font-semibold">TenderDoc Generator</p>
              <p className="text-xs text-slate-300">技术标生成工作台</p>
            </div>
          </div>

          <div className="max-w-xl py-12 lg:py-0">
            <h1 className="text-3xl font-semibold leading-tight sm:text-4xl">
              登录后继续处理招标文件
            </h1>
            <p className="mt-4 max-w-lg text-sm leading-7 text-slate-300">
              管理员负责账户和知识库权限，普通账户可用验证码注册后进入工作台。
            </p>
          </div>

          <div className="grid gap-3 text-sm text-slate-200 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
            <div className="rounded-lg border border-white/15 bg-white/5 p-3">
              <p className="font-medium text-white">解析</p>
              <p className="mt-1 text-xs leading-5 text-slate-300">抽取资质、评分、废标项</p>
            </div>
            <div className="rounded-lg border border-white/15 bg-white/5 p-3">
              <p className="font-medium text-white">生成</p>
              <p className="mt-1 text-xs leading-5 text-slate-300">套用企业技术标章节</p>
            </div>
            <div className="rounded-lg border border-white/15 bg-white/5 p-3">
              <p className="font-medium text-white">审查</p>
              <p className="mt-1 text-xs leading-5 text-slate-300">定位遗漏和风险响应</p>
            </div>
          </div>
        </section>

        <section className="flex items-center justify-center px-4 py-10 sm:px-6">
          <div className="w-full max-w-md rounded-lg border border-line bg-panel shadow-panel">
            <div className="border-b border-line px-6 py-5">
              <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-md bg-blue-50 text-brand">
                {accountType === "admin" ? (
                  <ShieldCheck className="h-5 w-5" />
                ) : (
                  <User className="h-5 w-5" />
                )}
              </div>
              <h2 className="text-xl font-semibold text-ink">
                {isRegistering ? "普通账户注册" : "账号登录"}
              </h2>
              <p className="mt-2 text-sm leading-6 text-muted">
                {isRegistering
                  ? "输入管理员提供的验证码创建普通账户。"
                  : "选择账户类型后进入工作台。"}
              </p>
            </div>

            <div className="border-b border-line px-6 py-4">
              <div className="grid grid-cols-2 gap-2 rounded-lg bg-field p-1">
                <button
                  type="button"
                  className={`inline-flex h-10 items-center justify-center gap-2 rounded-md text-sm font-semibold ${
                    accountType === "admin"
                      ? "bg-white text-ink shadow-sm"
                      : "text-muted hover:text-ink"
                  }`}
                  onClick={() => selectAccountType("admin")}
                >
                  <ShieldCheck className="h-4 w-4" />
                  管理员
                </button>
                <button
                  type="button"
                  className={`inline-flex h-10 items-center justify-center gap-2 rounded-md text-sm font-semibold ${
                    accountType === "user"
                      ? "bg-white text-ink shadow-sm"
                      : "text-muted hover:text-ink"
                  }`}
                  onClick={() => selectAccountType("user")}
                >
                  <User className="h-4 w-4" />
                  普通账户
                </button>
              </div>
            </div>

            <form className="space-y-4 px-6 py-5" onSubmit={submit}>
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">
                  账号
                </span>
                <span className="flex h-11 items-center gap-2 rounded-md border border-line bg-field px-3 focus-within:border-brand">
                  <User className="h-4 w-4 shrink-0 text-muted" />
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                    autoComplete="username"
                    placeholder={accountType === "admin" ? "管理员账号" : "普通账号"}
                  />
                </span>
              </label>

              {isRegistering ? (
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-muted">
                    显示名称
                  </span>
                  <span className="flex h-11 items-center gap-2 rounded-md border border-line bg-field px-3 focus-within:border-brand">
                    <UserPlus className="h-4 w-4 shrink-0 text-muted" />
                    <input
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                      autoComplete="name"
                      placeholder="显示名称"
                    />
                  </span>
                </label>
              ) : null}

              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">
                  密码
                </span>
                <span className="flex h-11 items-center gap-2 rounded-md border border-line bg-field px-3 focus-within:border-brand">
                  <LockKeyhole className="h-4 w-4 shrink-0 text-muted" />
                  <input
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                    type={showPassword ? "text" : "password"}
                    autoComplete={isRegistering ? "new-password" : "current-password"}
                    placeholder={isRegistering ? "至少 6 位" : "密码"}
                  />
                  <button
                    type="button"
                    title={showPassword ? "隐藏密码" : "显示密码"}
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted hover:bg-white"
                    onClick={() => setShowPassword((value) => !value)}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </span>
              </label>

              {isRegistering ? (
                <>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium text-muted">
                      确认密码
                    </span>
                    <span className="flex h-11 items-center gap-2 rounded-md border border-line bg-field px-3 focus-within:border-brand">
                      <LockKeyhole className="h-4 w-4 shrink-0 text-muted" />
                      <input
                        value={confirmPassword}
                        onChange={(event) => setConfirmPassword(event.target.value)}
                        className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                        type={showPassword ? "text" : "password"}
                        autoComplete="new-password"
                        placeholder="再次输入密码"
                      />
                    </span>
                  </label>

                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium text-muted">
                      管理员验证码
                    </span>
                    <span className="flex h-11 items-center gap-2 rounded-md border border-line bg-field px-3 focus-within:border-brand">
                      <KeyRound className="h-4 w-4 shrink-0 text-muted" />
                      <input
                        value={verificationCode}
                        onChange={(event) => setVerificationCode(event.target.value)}
                        className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                        autoComplete="one-time-code"
                        placeholder="例如 ABCD-2345"
                      />
                    </span>
                  </label>
                </>
              ) : null}

              <div className="flex items-center justify-between gap-3">
                <label className="inline-flex items-center gap-2 text-sm text-muted">
                  <input
                    checked={remember}
                    onChange={(event) => setRemember(event.target.checked)}
                    type="checkbox"
                    className="h-4 w-4 rounded border-line text-brand"
                  />
                  记住登录
                </label>
                {accountType === "admin" ? (
                  <button
                    type="button"
                    className="text-sm font-medium text-brand hover:underline"
                    onClick={fillDemoAccount}
                  >
                    填入默认账号
                  </button>
                ) : (
                  <button
                    type="button"
                    className="text-sm font-medium text-brand hover:underline"
                    onClick={() => {
                      setMode(isRegistering ? "login" : "register");
                      setError(null);
                    }}
                  >
                    {isRegistering ? "返回登录" : "注册普通账户"}
                  </button>
                )}
              </div>

              {error ? (
                <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-danger">
                  {error}
                </div>
              ) : null}

              <button
                type="submit"
                disabled={!canSubmit}
                className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isRegistering ? (
                  <UserPlus className="h-4 w-4" />
                ) : (
                  <LogIn className="h-4 w-4" />
                )}
                {isRegistering ? "注册并登录" : "登录"}
              </button>
            </form>

            <div className="border-t border-line bg-field px-6 py-4 text-xs leading-5 text-muted">
              默认管理员：admin / tenderdoc
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
