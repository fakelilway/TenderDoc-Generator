"use client";

import { useEffect, useState } from "react";
import { Building2, Check, Loader2 } from "lucide-react";
import { getCompanyProfile, saveCompanyProfile } from "@/lib/api";
import { getStoredSession } from "@/lib/auth";
import { ViewShell } from "@/components/ViewShell";
import { KnowledgePanel } from "@/components/KnowledgePanel";
import { PerformanceArchivePanel } from "@/components/PerformanceArchivePanel";
import { CertArchivePanel } from "@/components/CertArchivePanel";
import type { CompanyProfile } from "@/lib/types";

const emptyProfile: CompanyProfile = {
  company_name: "",
  credit_code: "",
  legal_representative: "",
  registered_capital: "",
  establish_date: "",
  registered_address: "",
  company_type: "",
  business_scope: "",
  qualification_grade: "",
  safety_license_no: "",
  contact_person: "",
  contact_phone: "",
  bank_name: "",
  bank_account: "",
  project_manager_name: "",
  project_manager_cert: "",
  postal_code: "",
  fax: "",
  email: "",
  legal_rep_title: "",
  legal_rep_phone: "",
  tech_director_name: "",
  tech_director_title: "",
  tech_director_phone: "",
  employee_total: "",
  project_manager_count: "",
  senior_title_count: "",
  mid_title_count: "",
  junior_title_count: "",
  technician_count: "",
  shareholders: "",
  business_term: "",
  registered_capital_words: ""
};

const fieldGroups: Array<{
  title: string;
  fields: Array<{ key: keyof CompanyProfile; label: string; placeholder?: string; wide?: boolean }>;
}> = [
  {
    title: "工商信息",
    fields: [
      { key: "company_name", label: "公司名称" },
      { key: "credit_code", label: "统一社会信用代码" },
      { key: "legal_representative", label: "法定代表人" },
      { key: "registered_capital", label: "注册资本", placeholder: "例如：壹亿零陆拾万元整" },
      { key: "establish_date", label: "成立日期", placeholder: "例如：2011-07-05" },
      { key: "company_type", label: "公司类型", placeholder: "例如：有限责任公司" },
      { key: "registered_address", label: "注册地址", wide: true },
      { key: "business_scope", label: "经营范围", wide: true }
    ]
  },
  {
    title: "资质与许可",
    fields: [
      { key: "qualification_grade", label: "资质等级", placeholder: "例如：公路工程施工总承包贰级" },
      { key: "safety_license_no", label: "安全生产许可证号" }
    ]
  },
  {
    title: "联系与账户",
    fields: [
      { key: "contact_person", label: "联系人" },
      { key: "contact_phone", label: "联系电话" },
      { key: "bank_name", label: "开户银行" },
      { key: "bank_account", label: "银行账号" }
    ]
  },
  {
    title: "潜在项目班子",
    fields: [
      { key: "project_manager_name", label: "潜在项目经理人选" },
      { key: "project_manager_cert", label: "项目经理建造师证号" }
    ]
  },
  {
    title: "法定代表人与技术负责人",
    fields: [
      { key: "legal_rep_title", label: "法定代表人技术职称" },
      { key: "legal_rep_phone", label: "法定代表人电话" },
      { key: "tech_director_name", label: "技术负责人" },
      { key: "tech_director_title", label: "技术负责人技术职称" },
      { key: "tech_director_phone", label: "技术负责人电话" }
    ]
  },
  {
    title: "人员构成",
    fields: [
      { key: "employee_total", label: "员工总人数" },
      { key: "project_manager_count", label: "项目经理/注册建造师人数" },
      { key: "senior_title_count", label: "高级职称人员数" },
      { key: "mid_title_count", label: "中级职称人员数" },
      { key: "junior_title_count", label: "初级职称人员数" },
      { key: "technician_count", label: "技工人数" }
    ]
  },
  {
    title: "通讯与股东",
    fields: [
      { key: "postal_code", label: "邮政编码" },
      { key: "fax", label: "传真" },
      { key: "email", label: "电子邮件" },
      { key: "business_term", label: "经营期限", wide: true },
      { key: "registered_capital_words", label: "注册资本(大写)", wide: true },
      { key: "shareholders", label: "股东及股权比例", wide: true }
    ]
  }
];

export function CompanyProfileView() {
  const session = getStoredSession();
  const canEdit = session?.role === "admin";
  const [profile, setProfile] = useState<CompanyProfile>(emptyProfile);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCompanyProfile()
      .then((response) => {
        setProfile({ ...emptyProfile, ...response.profile });
        setUpdatedAt(response.updated_at);
      })
      .catch((loadError) =>
        setError(loadError instanceof Error ? loadError.message : "档案加载失败")
      )
      .finally(() => setLoading(false));
  }, []);

  function setField(key: keyof CompanyProfile, value: string) {
    setSaved(false);
    setProfile((current) => ({ ...current, [key]: value }));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const response = await saveCompanyProfile(profile);
      setProfile({ ...emptyProfile, ...response.profile });
      setUpdatedAt(response.updated_at);
      setSaved(true);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "档案保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ViewShell title="公司档案" icon={Building2} maxWidth="4xl">
      <div className="space-y-4">
        <p className="rounded-md border border-line bg-white px-4 py-3 text-sm leading-6 text-muted">
          这里填写的企业信息会在生成标书时自动填入投标人基本状况表、投标函落款和资格审查资料，
          避免关键字段留白。信息以人工核实为准，系统不会用 OCR 识别证件图片来填写这些字段。
          下方「证件 / 人员 / 业绩 资料库」存放公司固定的扫描件（公司证件、人员证件、业绩证明等），
          每个项目自动复用；「知识库」只保留施工组织设计语料（施工方案）。
          {canEdit ? "" : "（查看模式：编辑需要管理员账户）"}
        </p>

        {error ? (
          <div className="rounded-md border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center gap-2 rounded-md border border-line bg-white px-4 py-6 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载企业档案...
          </div>
        ) : (
          <>
            {fieldGroups.map((group) => (
              <section key={group.title} className="rounded-lg border border-line bg-white p-4">
                <h2 className="mb-3 text-sm font-semibold text-ink">{group.title}</h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  {group.fields.map((field) => (
                    <label key={field.key} className={field.wide ? "sm:col-span-2" : ""}>
                      <span className="mb-1 block text-xs font-medium text-muted">
                        {field.label}
                      </span>
                      <input
                        value={profile[field.key]}
                        placeholder={field.placeholder ?? ""}
                        disabled={!canEdit}
                        onChange={(event) => setField(field.key, event.target.value)}
                        className="h-9 w-full rounded-md border border-line bg-field px-3 text-sm text-ink outline-none focus:border-brand disabled:cursor-not-allowed disabled:text-muted"
                      />
                    </label>
                  ))}
                </div>
              </section>
            ))}

            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">
                {updatedAt
                  ? `上次更新：${new Date(updatedAt).toLocaleString("zh-CN")}`
                  : "尚未保存过企业档案"}
              </span>
              {canEdit ? (
                <button
                  type="button"
                  disabled={saving}
                  onClick={handleSave}
                  className="inline-flex h-10 items-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : saved ? (
                    <Check className="h-4 w-4" />
                  ) : null}
                  {saved ? "已保存" : "保存档案"}
                </button>
              ) : null}
            </div>
          </>
        )}

        <section className="rounded-lg border border-line bg-white p-4">
          <h2 className="mb-1 text-sm font-semibold text-ink">业绩档案整理</h2>
          <p className="mb-3 text-xs leading-5 text-muted">
            把业绩台账和它的证明扫描件（中标通知书 / 合同 / 交工验收）按项目对上号。
            ⚠️待确认的扫一眼是否同一项目；📷待认领的从下拉里选对应台账认领；📄缺证明的需补扫描件。
          </p>
          <PerformanceArchivePanel />
        </section>

        <section className="rounded-lg border border-line bg-white p-4">
          <h2 className="mb-1 text-sm font-semibold text-ink">证件档案整理</h2>
          <p className="mb-3 text-xs leading-5 text-muted">
            人员证件按"人"归到一起、公司证件按"证件类型"归到一起。看图 / 改归属 / 合并同一个人 / 改名。
            身份证正反面、营业执照正副本、多页材料都保留，不会当重复删。
          </p>
          <CertArchivePanel />
        </section>

        <KnowledgePanel scope="company" />
      </div>
    </ViewShell>
  );
}
