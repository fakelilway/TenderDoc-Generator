"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Copy,
  KeyRound,
  Loader2,
  Save,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users
} from "lucide-react";
import {
  createRegistrationCode,
  createUser,
  deleteUser,
  listUsers,
  updateUserPermissions
} from "@/lib/api";
import { getStoredSession } from "@/lib/auth";
import type { UserAdminProfile } from "@/lib/types";

type CreateForm = {
  username: string;
  password: string;
  displayName: string;
};

const emptyForm: CreateForm = {
  username: "",
  password: "",
  displayName: ""
};

export function AdminUsersPanel() {
  const session = getStoredSession();
  const isAdmin = session?.role === "admin";
  const [users, setUsers] = useState<UserAdminProfile[]>([]);
  const [form, setForm] = useState<CreateForm>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [creatingCode, setCreatingCode] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [registrationCode, setRegistrationCode] = useState<{
    code: string;
    expiresAt: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshUsers = useCallback(async () => {
    if (!isAdmin) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await listUsers();
      setUsers(response.users);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "用户列表加载失败");
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    void refreshUsers();
  }, [refreshUsers]);

  if (!isAdmin) {
    return null;
  }

  async function submitCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.username.trim() || form.password.length < 6) {
      setError("账号不能为空，密码至少 6 位");
      return;
    }

    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      await createUser({
        username: form.username.trim(),
        password: form.password,
        display_name: form.displayName.trim() || null,
        can_view_knowledge: false,
        can_edit_knowledge: false
      });
      setForm(emptyForm);
      setNotice("账号已创建");
      await refreshUsers();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "账号创建失败");
    } finally {
      setCreating(false);
    }
  }

  function updateLocalUser(
    userId: number,
    patch: Partial<UserAdminProfile>
  ) {
    setUsers((current) =>
      current.map((user) =>
        user.id === userId
          ? {
              ...user,
              ...patch
            }
          : user
      )
    );
  }

  async function saveUser(user: UserAdminProfile) {
    setSavingId(user.id);
    setError(null);
    setNotice(null);
    try {
      const response = await updateUserPermissions(user.id, {
        display_name: user.display_name ?? null,
        is_active: user.role === "admin" ? true : user.is_active,
        can_view_knowledge: false,
        can_edit_knowledge: false
      });
      updateLocalUser(user.id, response.user);
      setNotice(`${response.user.username} 权限已保存`);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "权限保存失败");
    } finally {
      setSavingId(null);
    }
  }

  async function generateRegistrationCode() {
    setCreatingCode(true);
    setError(null);
    setNotice(null);
    try {
      const response = await createRegistrationCode();
      setRegistrationCode({
        code: response.code,
        expiresAt: response.expires_at
      });
      setNotice("注册验证码已生成");
    } catch (codeError) {
      setError(codeError instanceof Error ? codeError.message : "验证码生成失败");
    } finally {
      setCreatingCode(false);
    }
  }

  async function copyRegistrationCode() {
    if (!registrationCode) {
      return;
    }
    await navigator.clipboard.writeText(registrationCode.code);
    setNotice("验证码已复制");
  }

  async function removeUser(user: UserAdminProfile) {
    if (!window.confirm(`确认注销普通账号「${user.username}」？`)) {
      return;
    }
    setDeletingId(user.id);
    setError(null);
    setNotice(null);
    try {
      await deleteUser(user.id);
      setUsers((current) => current.filter((item) => item.id !== user.id));
      setNotice(`${user.username} 已注销`);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "账号注销失败");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-brand" />
          <h2 className="text-sm font-semibold text-ink">用户权限</h2>
        </div>
        {loading ? <Loader2 className="h-4 w-4 animate-spin text-muted" /> : null}
      </div>

      <form className="space-y-3 border-b border-line pb-4" onSubmit={submitCreate}>
        <div className="rounded-md border border-line bg-field p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-muted">
              <KeyRound className="h-3.5 w-3.5" />
              普通账户注册验证码
            </div>
            <button
              type="button"
              disabled={creatingCode}
              className="inline-flex h-8 items-center gap-2 rounded-md border border-line bg-white px-2 text-xs font-medium text-ink hover:bg-field disabled:text-muted"
              onClick={generateRegistrationCode}
            >
              {creatingCode ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <KeyRound className="h-3.5 w-3.5" />
              )}
              生成
            </button>
          </div>
          {registrationCode ? (
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1 rounded-md border border-line bg-white px-3 py-2">
                <p className="truncate text-sm font-semibold tracking-wide text-ink">
                  {registrationCode.code}
                </p>
                <p className="mt-1 text-xs text-muted">
                  有效期至 {new Date(registrationCode.expiresAt).toLocaleString("zh-CN")}
                </p>
              </div>
              <button
                type="button"
                title="复制验证码"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-ink text-white hover:bg-slate-700"
                onClick={copyRegistrationCode}
              >
                <Copy className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <p className="text-xs leading-5 text-muted">
              生成后交给普通用户注册；验证码一次有效。
            </p>
          )}
        </div>

        <div className="grid gap-2">
          <input
            value={form.username}
            onChange={(event) =>
              setForm((current) => ({ ...current, username: event.target.value }))
            }
            className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
            placeholder="新账号"
            autoComplete="off"
          />
          <input
            value={form.displayName}
            onChange={(event) =>
              setForm((current) => ({ ...current, displayName: event.target.value }))
            }
            className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
            placeholder="显示名称"
            autoComplete="off"
          />
          <input
            value={form.password}
            onChange={(event) =>
              setForm((current) => ({ ...current, password: event.target.value }))
            }
            className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink"
            placeholder="初始密码"
            type="password"
            autoComplete="new-password"
          />
        </div>
        <div className="rounded-md border border-line bg-field px-3 py-2 text-xs leading-5 text-muted">
          新建账号默认为普通员工，只能生成标书；知识库维护由管理员账户处理。
        </div>
        <button
          type="submit"
          disabled={creating}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
        >
          {creating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <UserPlus className="h-4 w-4" />
          )}
          创建普通账号
        </button>
      </form>

      {error ? (
        <div className="mt-3 rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-xs leading-5 text-danger">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="mt-3 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs leading-5 text-ok">
          {notice}
        </div>
      ) : null}

      <div className="mt-4 space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-muted">
          <Users className="h-3.5 w-3.5" />
          账号列表
        </div>
        <div className="max-h-80 space-y-2 overflow-auto">
          {users.map((user) => {
            const isRowAdmin = user.role === "admin";
            return (
              <div
                key={user.id}
                className="rounded-md border border-line bg-white px-3 py-3"
              >
                <div className="mb-2 flex items-center gap-2">
                  <input
                    value={user.display_name ?? ""}
                    onChange={(event) =>
                      updateLocalUser(user.id, {
                        display_name: event.target.value
                      })
                    }
                    className="h-8 min-w-0 flex-1 rounded-md border border-line bg-field px-2 text-xs text-ink"
                    placeholder={user.username}
                  />
                  <span className="rounded-md border border-line bg-field px-2 py-1 text-xs text-muted">
                    {isRowAdmin ? "admin" : "user"}
                  </span>
                </div>
                <p className="mb-2 truncate text-xs font-medium text-ink">
                  {user.username}
                </p>
                <div className="grid gap-2 text-xs text-muted">
                  <label className="inline-flex items-center gap-2">
                    <input
                      checked={isRowAdmin || user.is_active}
                      disabled={isRowAdmin}
                      onChange={(event) =>
                        updateLocalUser(user.id, {
                          is_active: event.target.checked
                        })
                      }
                      type="checkbox"
                      className="h-4 w-4 rounded border-line text-brand"
                    />
                    启用账号
                  </label>
                  <p className="rounded-md border border-line bg-field px-2 py-2 text-xs leading-5 text-muted">
                    普通员工可查看和检索知识库；添加、删除、编辑资料仅管理员可操作。
                  </p>
                </div>
                <button
                  type="button"
                  disabled={savingId === user.id}
                  className="mt-3 inline-flex h-8 w-full items-center justify-center gap-2 rounded-md border border-line bg-white text-xs font-medium text-ink hover:bg-field disabled:text-muted"
                  onClick={() => saveUser(user)}
                >
                  {savingId === user.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  保存权限
                </button>
                {!isRowAdmin ? (
                  <button
                    type="button"
                    disabled={deletingId === user.id}
                    className="mt-2 inline-flex h-8 w-full items-center justify-center gap-2 rounded-md border border-orange-200 bg-orange-50 text-xs font-medium text-danger hover:bg-orange-100 disabled:text-muted"
                    onClick={() => removeUser(user)}
                  >
                    {deletingId === user.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                    注销普通账号
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
