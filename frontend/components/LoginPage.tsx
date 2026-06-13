"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Eye,
  EyeOff,
  FileText,
  KeyRound,
  Loader2,
  LockKeyhole,
  LogIn,
  ShieldCheck,
  User,
  UserPlus
} from "lucide-react";
import { AppLogo } from "@/components/AppLogo";
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
    <main className="min-h-screen bg-[#eef1f5] p-3 text-[#1f2937] sm:p-5">
      <div className="relative mx-auto min-h-[calc(100vh-24px)] max-w-[1540px] overflow-hidden rounded-[28px] border border-white/70 bg-[linear-gradient(135deg,#ffffff_0%,#f7f9fc_45%,#eef3f8_100%)] shadow-[0_28px_90px_rgba(15,23,42,0.10)] sm:min-h-[calc(100vh-40px)]">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_26%_20%,rgba(255,255,255,0.95),rgba(255,255,255,0)_32%),radial-gradient(circle_at_72%_38%,rgba(255,255,255,0.72),rgba(255,255,255,0)_28%)]" />
        <div className="relative grid min-h-[calc(100vh-24px)] gap-8 px-6 py-7 sm:min-h-[calc(100vh-40px)] sm:px-10 lg:grid-cols-[minmax(0,1fr)_590px] lg:px-16 lg:py-14">
          <section className="relative flex min-h-[560px] flex-col justify-between overflow-hidden pb-4">
            <div className="flex items-center gap-4">
              <AppLogo className="h-16 w-16 rounded-[18px] bg-white/80 p-1 shadow-[0_12px_30px_rgba(8,42,85,0.10)]" />
              <div>
                <div
                  className="bg-[linear-gradient(105deg,#082a55_0%,#082a55_50%,#b88a45_52%,#c99d5b_100%)] bg-clip-text text-[28px] font-black leading-none tracking-[0.2em] text-transparent sm:text-[34px]"
                  style={{
                    fontFamily:
                      '"Songti SC", "STSong", "SimSun", "PingFang SC", serif'
                  }}
                >
                  正奇建设
                </div>
                <p className="mt-2 text-[11px] font-semibold tracking-[0.32em] text-[#4b5563]">
                  ZHENGQI CONSTRUCTION
                </p>
              </div>
            </div>

            <div className="relative z-10 max-w-[620px] pb-10 pt-14 lg:pb-24 lg:pt-0">
              <h1 className="text-[34px] font-semibold leading-tight tracking-[-0.02em] text-[#111827] sm:text-[44px]">
                标书生成工作台
              </h1>
              <p className="mt-5 text-lg font-medium tracking-[0.04em] text-[#6b7280]">
                智能、高效、合规的标书生成解决方案
              </p>

              <div className="mt-12 grid max-w-lg gap-9">
                {[
                  {
                    title: "智能解析",
                    copy: "自动识别招标文件要求，精准提取关键信息",
                    icon: ShieldCheck,
                    tone: "bg-[#e8f0ff] text-[#2f7cf6]"
                  },
                  {
                    title: "高效生成",
                    copy: "基于知识库与模板，快速生成专业标书内容",
                    icon: FileText,
                    tone: "bg-[#eaf8ef] text-[#34a853]"
                  },
                  {
                    title: "合规风控",
                    copy: "内置合规检查机制，降低风险，提高中标率",
                    icon: KeyRound,
                    tone: "bg-[#fff3e6] text-[#d38322]"
                  }
                ].map((item) => {
                  const Icon = item.icon;
                  return (
                    <div key={item.title} className="flex items-start gap-5">
                      <span
                        className={`grid h-[58px] w-[58px] shrink-0 place-items-center rounded-full ${item.tone}`}
                      >
                        <Icon className="h-6 w-6" />
                      </span>
                      <div>
                        <p className="text-base font-semibold text-[#1f2937]">
                          {item.title}
                        </p>
                        <p className="mt-2 text-sm leading-6 text-[#6b7280]">
                          {item.copy}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="pointer-events-none absolute bottom-12 left-[38%] hidden h-[360px] w-[420px] opacity-[0.18] lg:block">
              <div className="absolute bottom-0 left-10 h-[250px] w-[92px] skew-x-[-8deg] border border-[#8da1b8]/70 bg-white/30" />
              <div className="absolute bottom-0 left-24 h-[320px] w-[126px] skew-x-[-8deg] border border-[#8da1b8]/70 bg-white/30" />
              <div className="absolute bottom-0 left-48 h-[190px] w-[96px] skew-x-[-8deg] border border-[#8da1b8]/55 bg-white/20" />
              <div className="absolute bottom-8 left-0 h-[22px] w-[440px] -rotate-6 rounded-full border-t border-[#c8a36a]/70" />
              <div className="absolute bottom-0 left-8 h-px w-[390px] bg-[#d4dde8]" />
            </div>

            <p className="relative z-10 text-sm font-medium tracking-[0.28em] text-[#6b7280]">
              守正出奇 · 匠心致远
            </p>
          </section>

          <section className="flex items-center justify-center py-6 lg:py-0">
            <div className="w-full max-w-[570px] rounded-[24px] border border-white/80 bg-white/82 px-10 py-9 shadow-[0_30px_90px_rgba(15,23,42,0.10)] backdrop-blur-2xl">
              <div className="mb-7 flex h-[52px] w-[52px] items-center justify-center rounded-[12px] bg-[#eef4ff] text-[#2f7cf6]">
                {accountType === "admin" ? (
                  <ShieldCheck className="h-5 w-5" />
                ) : (
                  <User className="h-5 w-5" />
                )}
              </div>
              <h2 className="text-[28px] font-semibold tracking-[-0.02em] text-[#111827]">
                {isRegistering ? "普通账户注册" : "欢迎登录"}
              </h2>
              <p className="mt-3 text-base leading-7 text-[#6b7280]">
                {isRegistering
                  ? "输入管理员提供的验证码创建普通账户。"
                  : "登录后继续使用正奇标书生成工作台"}
              </p>

              <div className="mt-8 grid grid-cols-2 gap-1.5 rounded-[15px] border border-[#dce3ee] bg-[#f6f8fb] p-1.5">
                <button
                  type="button"
                  className={`inline-flex h-12 items-center justify-center gap-2 rounded-[12px] text-sm font-semibold transition ${
                    accountType === "admin"
                      ? "bg-white text-[#1f2937] shadow-[0_8px_20px_rgba(15,23,42,0.07)]"
                      : "text-[#6b7280] hover:bg-white/60 hover:text-[#1f2937]"
                  }`}
                  onClick={() => selectAccountType("admin")}
                >
                  <ShieldCheck className="h-4 w-4" />
                  管理员
                </button>
                <button
                  type="button"
                  className={`inline-flex h-12 items-center justify-center gap-2 rounded-[12px] text-sm font-semibold transition ${
                    accountType === "user"
                      ? "bg-white text-[#1f2937] shadow-[0_8px_20px_rgba(15,23,42,0.07)]"
                      : "text-[#6b7280] hover:bg-white/60 hover:text-[#1f2937]"
                  }`}
                  onClick={() => selectAccountType("user")}
                >
                  <User className="h-4 w-4" />
                  普通账户
                </button>
              </div>

            <form className="mt-8 space-y-5" onSubmit={submit}>
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-[#6b7280]">
                  账号
                </span>
                <span className="flex h-14 items-center gap-3 rounded-[13px] border border-[#dce3ee] bg-white px-4 focus-within:border-[#2f7cf6]">
                  <User className="h-5 w-5 shrink-0 text-[#8a94a6]" />
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    className="h-full min-w-0 flex-1 bg-transparent text-sm text-[#1f2937] outline-none placeholder:text-[#a5adba]"
                    autoComplete="username"
                    placeholder="请输入账号"
                  />
                </span>
              </label>

              {isRegistering ? (
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-[#6b7280]">
                    显示名称
                  </span>
                  <span className="flex h-14 items-center gap-3 rounded-[13px] border border-[#dce3ee] bg-white px-4 focus-within:border-[#2f7cf6]">
                    <UserPlus className="h-5 w-5 shrink-0 text-[#8a94a6]" />
                    <input
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      className="h-full min-w-0 flex-1 bg-transparent text-sm text-[#1f2937] outline-none placeholder:text-[#a5adba]"
                      autoComplete="name"
                      placeholder="显示名称"
                    />
                  </span>
                </label>
              ) : null}

              <label className="block">
                <span className="mb-2 block text-sm font-medium text-[#6b7280]">
                  密码
                </span>
                <span className="flex h-14 items-center gap-3 rounded-[13px] border border-[#dce3ee] bg-white px-4 focus-within:border-[#2f7cf6]">
                  <LockKeyhole className="h-5 w-5 shrink-0 text-[#8a94a6]" />
                  <input
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="h-full min-w-0 flex-1 bg-transparent text-sm text-[#1f2937] outline-none placeholder:text-[#a5adba]"
                    type={showPassword ? "text" : "password"}
                    autoComplete={isRegistering ? "new-password" : "current-password"}
                    placeholder={isRegistering ? "至少 6 位" : "请输入密码"}
                  />
                  <button
                    type="button"
                    title={showPassword ? "隐藏密码" : "显示密码"}
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#8a94a6] hover:bg-[#f3f6fb]"
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
                    <span className="mb-2 block text-sm font-medium text-[#6b7280]">
                      确认密码
                    </span>
                    <span className="flex h-14 items-center gap-3 rounded-[13px] border border-[#dce3ee] bg-white px-4 focus-within:border-[#2f7cf6]">
                      <LockKeyhole className="h-5 w-5 shrink-0 text-[#8a94a6]" />
                      <input
                        value={confirmPassword}
                        onChange={(event) => setConfirmPassword(event.target.value)}
                        className="h-full min-w-0 flex-1 bg-transparent text-sm text-[#1f2937] outline-none placeholder:text-[#a5adba]"
                        type={showPassword ? "text" : "password"}
                        autoComplete="new-password"
                        placeholder="再次输入密码"
                      />
                    </span>
                  </label>

                  <label className="block">
                    <span className="mb-2 block text-sm font-medium text-[#6b7280]">
                      管理员验证码
                    </span>
                    <span className="flex h-14 items-center gap-3 rounded-[13px] border border-[#dce3ee] bg-white px-4 focus-within:border-[#2f7cf6]">
                      <KeyRound className="h-5 w-5 shrink-0 text-[#8a94a6]" />
                      <input
                        value={verificationCode}
                        onChange={(event) => setVerificationCode(event.target.value)}
                        className="h-full min-w-0 flex-1 bg-transparent text-sm text-[#1f2937] outline-none placeholder:text-[#a5adba]"
                        autoComplete="one-time-code"
                        placeholder="例如 ABCD-2345"
                      />
                    </span>
                  </label>
                </>
              ) : null}

              <div className="flex items-center justify-between gap-3">
                <label className="inline-flex items-center gap-2 text-sm text-[#6b7280]">
                  <input
                    checked={remember}
                    onChange={(event) => setRemember(event.target.checked)}
                    type="checkbox"
                    className="h-4 w-4 rounded border-[#dce3ee] text-[#2f7cf6]"
                  />
                  记住登录状态
                </label>
                {accountType === "admin" ? (
                  <button
                    type="button"
                    className="text-sm font-semibold text-[#2f7cf6] hover:underline"
                    onClick={fillDemoAccount}
                  >
                    填入默认账号
                  </button>
                ) : (
                  <button
                    type="button"
                    className="text-sm font-semibold text-[#2f7cf6] hover:underline"
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
                <div className="rounded-[13px] border border-[#ff9f0a]/20 bg-[#fff4df]/85 px-3 py-2 text-sm text-[#b45309]">
                  {error}
                </div>
              ) : null}

              <button
                type="submit"
                disabled={!canSubmit}
                className="inline-flex h-14 w-full items-center justify-center gap-2 rounded-[13px] bg-[linear-gradient(135deg,#4b93ff_0%,#246bff_100%)] px-4 text-sm font-semibold tracking-[0.18em] text-white shadow-[0_16px_34px_rgba(47,124,246,0.28)] transition hover:brightness-105 disabled:cursor-not-allowed disabled:bg-[#b7c6d8] disabled:shadow-none"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isRegistering ? (
                  <UserPlus className="h-4 w-4" />
                ) : (
                  <LogIn className="h-4 w-4" />
                )}
                {isRegistering ? "注册并登录" : "登 录"}
              </button>
            </form>

            <div className="mt-6 border-t border-[#edf0f5] pt-5 text-xs leading-5 text-[#8a94a6]">
              默认管理员：admin / tenderdoc
            </div>
          </div>
        </section>
      </div>
      </div>
    </main>
  );
}
