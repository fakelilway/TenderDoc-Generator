"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  Database,
  Eye,
  FileText,
  Layers3,
  Loader2,
  LockKeyhole,
  Pencil,
  Search,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import {
  deleteKnowledgeDocument,
  getKnowledgeDocumentPreview,
  listKnowledgeDocuments,
  renameKnowledgeDocument,
  searchKnowledge,
  uploadKnowledge
} from "@/lib/api";
import { getStoredSession } from "@/lib/auth";
import type {
  KnowledgeDocumentPreview,
  KnowledgeDocumentSummary,
  KnowledgeSearchResult
} from "@/lib/types";

function metadataText(result: KnowledgeSearchResult) {
  const fileName = result.metadata.file_name;
  if (typeof fileName === "string" && fileName) {
    return fileName;
  }
  return result.document_id ? `Document ${result.document_id}` : "知识库片段";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

const projectTypeOptions = ["公路工程", "市政道路", "桥梁涵洞", "交通安全设施", "养护维修", "改建扩建", "排水管网"];
const documentCategoryOptions = ["企业证件", "人员证件", "业绩证明", "历史投标文件", "施工方案", "报价清单", "规范标准", "图片附件"];
const volumeOptions = ["商务文件", "资格文件", "技术文件", "报价文件", "附图附表"];
const specialtyOptions = ["路基", "路面", "桥涵", "交安", "排水", "照明", "绿化", "质量", "安全", "进度", "环保"];
const ownerTypeOptions = ["公司", "人员", "项目"];
const certificateTypeOptions = ["营业执照", "资质证书", "安全生产许可证", "一级建造师证", "二级建造师证", "身份证", "建安证", "交安证", "职称证", "社保", "业绩"];
const sensitivityOptions = ["普通", "内部", "敏感", "高敏感"];
const usageScopeOptions = ["可用于RAG正文", "仅作证明附件", "可插图", "禁止进入大模型"];
const verifiedStatusOptions = ["未核验", "已核验", "已过期", "需更新"];

type KnowledgeMetaDraft = {
  projectType: string;
  documentType: string;
  documentCategory: string;
  specialty: string;
  volume: string;
  region: string;
  projectYear: string;
  ownerType: string;
  ownerName: string;
  certificateType: string;
  validFrom: string;
  validTo: string;
  sensitivity: string;
  usageScope: string;
  verifiedStatus: string;
  imageInsertable: boolean;
  tagText: string;
};

function emptyMetaDraft(): KnowledgeMetaDraft {
  return {
    projectType: "",
    documentType: "",
    documentCategory: "",
    specialty: "",
    volume: "",
    region: "",
    projectYear: "",
    ownerType: "",
    ownerName: "",
    certificateType: "",
    validFrom: "",
    validTo: "",
    sensitivity: "",
    usageScope: "",
    verifiedStatus: "",
    imageInsertable: true,
    tagText: ""
  };
}

function metaDraftFromDocument(document: KnowledgeDocumentSummary): KnowledgeMetaDraft {
  return {
    projectType: document.project_type ?? "",
    documentType: document.document_type ?? "",
    documentCategory: document.document_category ?? "",
    specialty: document.specialty ?? "",
    volume: document.volume ?? "",
    region: document.region ?? "",
    projectYear: document.project_year ? String(document.project_year) : "",
    ownerType: document.owner_type ?? "",
    ownerName: document.owner_name ?? "",
    certificateType: document.certificate_type ?? "",
    validFrom: document.valid_from ?? "",
    validTo: document.valid_to ?? "",
    sensitivity: document.sensitivity ?? "",
    usageScope: document.usage_scope ?? "",
    verifiedStatus: document.verified_status ?? "",
    imageInsertable: document.image_insertable ?? true,
    tagText: (document.tags ?? []).join(", ")
  };
}

function splitTags(value: string) {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function isImageFile(file: File | null) {
  return Boolean(file?.type.startsWith("image/") || /\.(jpe?g|png|gif|webp)$/i.test(file?.name ?? ""));
}

function compactMeta(document: KnowledgeDocumentSummary) {
  return [
    document.project_type,
    document.volume,
    document.document_category ?? document.document_type,
    document.specialty,
    document.region,
    document.certificate_type,
    document.owner_name,
    document.verified_status,
    document.valid_to ? `有效期至${document.valid_to}` : null,
    ...(document.tags ?? [])
  ].filter(Boolean);
}

function MetaSelect({
  value,
  onChange,
  placeholder,
  options
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
    >
      <option value="">{placeholder}</option>
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}

export function KnowledgePanel() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const session = getStoredSession();
  const isAdmin = session?.role === "admin";
  const canView = Boolean(session);
  const canEdit = isAdmin;
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [projectType, setProjectType] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [documentCategory, setDocumentCategory] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [volume, setVolume] = useState("");
  const [region, setRegion] = useState("");
  const [projectYear, setProjectYear] = useState("");
  const [ownerType, setOwnerType] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [certificateType, setCertificateType] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validTo, setValidTo] = useState("");
  const [sensitivity, setSensitivity] = useState("");
  const [usageScope, setUsageScope] = useState("");
  const [verifiedStatus, setVerifiedStatus] = useState("");
  const [imageInsertable, setImageInsertable] = useState(true);
  const [tagText, setTagText] = useState("");
  const [ingestionMode, setIngestionMode] = useState("auto");
  const [query, setQuery] = useState("施工组织设计 工期 质量 安全");
  const [results, setResults] = useState<KnowledgeSearchResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [editingMeta, setEditingMeta] = useState<KnowledgeMetaDraft>(emptyMetaDraft);
  const [preview, setPreview] = useState<KnowledgeDocumentPreview | null>(null);
  const [previewLoadingId, setPreviewLoadingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpload, setLastUpload] = useState<string | null>(null);

  const refreshDocuments = useCallback(async () => {
    if (!canView) {
      return;
    }
    setLoadingDocuments(true);
    try {
      const response = await listKnowledgeDocuments();
      setDocuments(response.documents);
    } catch (listError) {
      setError(listError instanceof Error ? listError.message : "知识库加载失败");
    } finally {
      setLoadingDocuments(false);
    }
  }, [canView]);

  useEffect(() => {
    void refreshDocuments();
  }, [refreshDocuments]);

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setLastUpload(null);
    setError(null);
  }

  async function handleUpload() {
    if (!file || !canEdit) {
      return;
    }

    setBusy(true);
    setError(null);
    setLastUpload(null);
    try {
      const response = await uploadKnowledge(file, {
        documentType: documentType.trim() || undefined,
        projectType: projectType.trim() || undefined,
        documentCategory: documentCategory.trim() || undefined,
        specialty: specialty.trim() || undefined,
        volume: volume.trim() || undefined,
        region: region.trim() || undefined,
        projectYear: projectYear.trim() ? Number(projectYear) : null,
        ownerType: ownerType.trim() || undefined,
        ownerName: ownerName.trim() || undefined,
        certificateType: certificateType.trim() || undefined,
        validFrom: validFrom.trim() || undefined,
        validTo: validTo.trim() || undefined,
        sensitivity: sensitivity.trim() || undefined,
        usageScope: usageScope.trim() || undefined,
        verifiedStatus: verifiedStatus.trim() || undefined,
        imageInsertable: isImageFile(file) ? imageInsertable : undefined,
        tags: splitTags(tagText),
        ingestionMode: ingestionMode === "auto" ? undefined : ingestionMode
      });
      const statusText =
        response.indexing_status === "evidence_only"
          ? "仅存证据"
          : `${response.chunk_ids.length} 个片段`;
      setLastUpload(`${file.name}：${statusText}`);
      setFile(null);
      setProjectType("");
      setDocumentType("");
      setDocumentCategory("");
      setSpecialty("");
      setVolume("");
      setRegion("");
      setProjectYear("");
      setOwnerType("");
      setOwnerName("");
      setCertificateType("");
      setValidFrom("");
      setValidTo("");
      setSensitivity("");
      setUsageScope("");
      setVerifiedStatus("");
      setImageInsertable(true);
      setTagText("");
      setIngestionMode("auto");
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await refreshDocuments();
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "知识库上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSearch(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const value = query.trim();
    if (!value || !canView) {
      return;
    }

    setSearching(true);
    setError(null);
    try {
      const response = await searchKnowledge(value, 5, {
        projectType: projectType.trim() || undefined,
        documentType: documentType.trim() || undefined,
        documentCategory: documentCategory.trim() || undefined,
        specialty: specialty.trim() || undefined,
        volume: volume.trim() || undefined,
        region: region.trim() || undefined,
        certificateType: certificateType.trim() || undefined,
        sensitivity: sensitivity.trim() || undefined,
        usageScope: usageScope.trim() || undefined,
        verifiedStatus: verifiedStatus.trim() || undefined,
        tags: splitTags(tagText)
      });
      setResults(response.results);
    } catch (searchError) {
      setError(searchError instanceof Error ? searchError.message : "知识库检索失败");
    } finally {
      setSearching(false);
    }
  }

  function startEditing(document: KnowledgeDocumentSummary) {
    setEditingId(document.document_id);
    setEditingTitle(document.file_name);
    setEditingMeta(metaDraftFromDocument(document));
    setError(null);
  }

  async function saveTitle(documentId: number) {
    const title = editingTitle.trim();
    if (!title) {
      setError("标题不能为空");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await renameKnowledgeDocument(documentId, title, {
        projectType: editingMeta.projectType.trim() || null,
        documentType: editingMeta.documentType.trim() || null,
        documentCategory: editingMeta.documentCategory.trim() || null,
        specialty: editingMeta.specialty.trim() || null,
        volume: editingMeta.volume.trim() || null,
        region: editingMeta.region.trim() || null,
        projectYear: editingMeta.projectYear.trim()
          ? Number(editingMeta.projectYear)
          : null,
        ownerType: editingMeta.ownerType.trim() || null,
        ownerName: editingMeta.ownerName.trim() || null,
        certificateType: editingMeta.certificateType.trim() || null,
        validFrom: editingMeta.validFrom.trim() || null,
        validTo: editingMeta.validTo.trim() || null,
        sensitivity: editingMeta.sensitivity.trim() || null,
        usageScope: editingMeta.usageScope.trim() || null,
        verifiedStatus: editingMeta.verifiedStatus.trim() || null,
        imageInsertable: editingMeta.imageInsertable,
        tags: splitTags(editingMeta.tagText)
      });
      setEditingId(null);
      setEditingTitle("");
      setResults([]);
      await refreshDocuments();
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "标题更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteDocument(document: KnowledgeDocumentSummary) {
    if (!window.confirm(`确认从知识库删除「${document.file_name}」？`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteKnowledgeDocument(document.document_id);
      setResults((current) =>
        current.filter((result) => result.document_id !== document.document_id)
      );
      await refreshDocuments();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "知识库删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function previewDocument(document: KnowledgeDocumentSummary) {
    setPreviewLoadingId(document.document_id);
    setError(null);
    try {
      const response = await getKnowledgeDocumentPreview(document.document_id);
      setPreview(response);
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "资料预览失败");
    } finally {
      setPreviewLoadingId(null);
    }
  }

  const totalChunks = documents.reduce(
    (sum, document) => sum + document.chunk_count,
    0
  );

  if (!canView) {
    return (
      <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
        <div className="mb-4 flex items-center gap-2">
          <Database className="h-4 w-4 text-brand" />
          <h2 className="text-sm font-semibold text-ink">知识库</h2>
        </div>
        <div className="rounded-md border border-dashed border-line bg-field px-3 py-4 text-center">
          <LockKeyhole className="mx-auto mb-2 h-5 w-5 text-muted" />
          <p className="text-sm font-medium text-ink">暂无知识库权限</p>
          <p className="mt-1 text-xs leading-5 text-muted">
            登录后可查看知识库；添加、删除和编辑资料需要管理员账户。
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-brand" />
          <h2 className="text-sm font-semibold text-ink">知识库</h2>
        </div>
        <span className="rounded-md border border-line bg-field px-2 py-1 text-xs font-medium text-muted">
          {documents.length} 文件 · {totalChunks} 片段
        </span>
      </div>

      <div className="space-y-4">
        {canEdit ? (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.doc,.docx,.txt,.md,.jpg,.jpeg,.png"
              className="hidden"
              onChange={chooseFile}
            />

            {file ? (
              <div className="flex items-center gap-3 rounded-md border border-line bg-field px-3 py-3">
                <FileText className="h-4 w-4 shrink-0 text-brand" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{file.name}</p>
                  <p className="text-xs text-muted">
                    {(file.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                </div>
                <button
                  type="button"
                  title="移除"
                  className="grid h-8 w-8 place-items-center rounded-md border border-line text-muted hover:bg-white"
                  onClick={() => {
                    setFile(null);
                    if (fileInputRef.current) {
                      fileInputRef.current.value = "";
                    }
                  }}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="flex min-h-24 w-full flex-col items-center justify-center rounded-lg border border-dashed border-line bg-field px-3 py-4 text-center hover:border-brand"
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadCloud className="mb-2 h-6 w-6 text-muted" />
                <span className="text-sm font-medium text-ink">
                  上传历史标书 / 企业资料
                </span>
                <span className="mt-1 text-xs text-muted">
                  PDF / DOC / DOCX / TXT / MD / JPG / PNG
                </span>
              </button>
            )}

            <div className="grid grid-cols-2 gap-2">
              <MetaSelect value={projectType} onChange={setProjectType} placeholder="项目类型" options={projectTypeOptions} />
              <MetaSelect value={volume} onChange={setVolume} placeholder="所属卷册" options={volumeOptions} />
              <MetaSelect value={documentCategory} onChange={setDocumentCategory} placeholder="资料类别" options={documentCategoryOptions} />
              <input
                value={documentType}
                onChange={(event) => setDocumentType(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="细分类型"
              />
              <MetaSelect value={specialty} onChange={setSpecialty} placeholder="专业" options={specialtyOptions} />
              <input
                value={region}
                onChange={(event) => setRegion(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="地区"
              />
              <input
                value={projectYear}
                onChange={(event) => setProjectYear(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="年份"
              />
              <MetaSelect value={ownerType} onChange={setOwnerType} placeholder="主体类型" options={ownerTypeOptions} />
              <input
                value={ownerName}
                onChange={(event) => setOwnerName(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="主体名称"
              />
              <MetaSelect value={certificateType} onChange={setCertificateType} placeholder="证件/证明" options={certificateTypeOptions} />
              <input
                value={validFrom}
                onChange={(event) => setValidFrom(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="有效期起 YYYY-MM-DD"
              />
              <input
                value={validTo}
                onChange={(event) => setValidTo(event.target.value)}
                className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="有效期至 YYYY-MM-DD"
              />
              <MetaSelect value={sensitivity} onChange={setSensitivity} placeholder="敏感级别" options={sensitivityOptions} />
              <MetaSelect value={usageScope} onChange={setUsageScope} placeholder="用途范围" options={usageScopeOptions} />
              <MetaSelect value={verifiedStatus} onChange={setVerifiedStatus} placeholder="核验状态" options={verifiedStatusOptions} />
              <label className="flex h-9 items-center gap-2 rounded-md border border-line bg-field px-3 text-xs text-ink">
                <input
                  type="checkbox"
                  checked={imageInsertable}
                  onChange={(event) => setImageInsertable(event.target.checked)}
                />
                可插图
              </label>
              <input
                value={tagText}
                onChange={(event) => setTagText(event.target.value)}
                className="col-span-2 h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
                placeholder="补充标签，逗号分隔"
              />
              <select
                value={ingestionMode}
                onChange={(event) => setIngestionMode(event.target.value)}
                className="col-span-2 h-9 rounded-md border border-line bg-field px-3 text-xs text-ink"
              >
                <option value="auto">自动判断摄入方式</option>
                <option value="rag_text">RAG 文本资料</option>
                <option value="structured_evidence">证件/证据资料</option>
                <option value="evidence_only">仅存原件不索引</option>
              </select>
            </div>

            <button
              type="button"
              disabled={!file || busy}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-brand px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
              onClick={handleUpload}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UploadCloud className="h-4 w-4" />
              )}
              上传入库
            </button>
          </>
        ) : (
          <div className="rounded-md border border-line bg-field px-3 py-3 text-xs leading-5 text-muted">
            普通账户可查看和检索知识库；上传、删除和标题编辑需要管理员账户。
          </div>
        )}

        <form className="space-y-2" onSubmit={handleSearch}>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">
              检索测试
            </span>
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-10 min-w-0 flex-1 rounded-md border border-line bg-field px-3 text-sm text-ink"
                placeholder="输入标书章节、工法、资质关键词"
              />
              <button
                type="submit"
                disabled={searching || !query.trim()}
                title="检索"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-ink text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {searching ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
              </button>
            </div>
          </label>
        </form>

        {error ? (
          <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-xs leading-5 text-danger">
            {error}
          </div>
        ) : null}

        {lastUpload ? (
          <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs leading-5 text-ok">
            {lastUpload}
          </div>
        ) : null}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-muted">入库文档</p>
            {loadingDocuments ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted" />
            ) : null}
          </div>
          <div className="max-h-48 space-y-2 overflow-auto">
            {documents.length === 0 ? (
              <div className="rounded-md border border-dashed border-line bg-field px-3 py-4 text-center text-xs text-muted">
                暂无知识库文档
              </div>
            ) : (
              documents.slice(0, 8).map((document) => (
                <div
                  key={document.document_id}
                  className="rounded-md border border-line bg-white px-3 py-2"
                >
                  {editingId === document.document_id ? (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <input
                          value={editingTitle}
                          onChange={(event) => setEditingTitle(event.target.value)}
                          className="h-8 min-w-0 flex-1 rounded-md border border-line bg-field px-2 text-xs text-ink"
                          autoFocus
                        />
                        <button
                          type="button"
                          title="保存"
                          disabled={busy}
                          className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-ok text-white disabled:bg-green-300"
                          onClick={() => saveTitle(document.document_id)}
                        >
                          {busy ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Check className="h-3.5 w-3.5" />
                          )}
                        </button>
                        <button
                          type="button"
                          title="取消"
                          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-line text-muted hover:bg-field"
                          onClick={() => setEditingId(null)}
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <MetaSelect value={editingMeta.projectType} onChange={(value) => setEditingMeta((current) => ({ ...current, projectType: value }))} placeholder="项目类型" options={projectTypeOptions} />
                        <MetaSelect value={editingMeta.volume} onChange={(value) => setEditingMeta((current) => ({ ...current, volume: value }))} placeholder="所属卷册" options={volumeOptions} />
                        <MetaSelect value={editingMeta.documentCategory} onChange={(value) => setEditingMeta((current) => ({ ...current, documentCategory: value }))} placeholder="资料类别" options={documentCategoryOptions} />
                        <input value={editingMeta.documentType} onChange={(event) => setEditingMeta((current) => ({ ...current, documentType: event.target.value }))} className="h-8 rounded-md border border-line bg-field px-2 text-xs text-ink" placeholder="细分类型" />
                        <MetaSelect value={editingMeta.specialty} onChange={(value) => setEditingMeta((current) => ({ ...current, specialty: value }))} placeholder="专业" options={specialtyOptions} />
                        <input value={editingMeta.region} onChange={(event) => setEditingMeta((current) => ({ ...current, region: event.target.value }))} className="h-8 rounded-md border border-line bg-field px-2 text-xs text-ink" placeholder="地区" />
                        <input value={editingMeta.ownerName} onChange={(event) => setEditingMeta((current) => ({ ...current, ownerName: event.target.value }))} className="h-8 rounded-md border border-line bg-field px-2 text-xs text-ink" placeholder="主体名称" />
                        <MetaSelect value={editingMeta.certificateType} onChange={(value) => setEditingMeta((current) => ({ ...current, certificateType: value }))} placeholder="证件/证明" options={certificateTypeOptions} />
                        <input value={editingMeta.validTo} onChange={(event) => setEditingMeta((current) => ({ ...current, validTo: event.target.value }))} className="h-8 rounded-md border border-line bg-field px-2 text-xs text-ink" placeholder="有效期至" />
                        <MetaSelect value={editingMeta.verifiedStatus} onChange={(value) => setEditingMeta((current) => ({ ...current, verifiedStatus: value }))} placeholder="核验状态" options={verifiedStatusOptions} />
                        <input value={editingMeta.tagText} onChange={(event) => setEditingMeta((current) => ({ ...current, tagText: event.target.value }))} className="col-span-2 h-8 rounded-md border border-line bg-field px-2 text-xs text-ink" placeholder="标签，逗号分隔" />
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-2">
                      <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-ink">
                          {document.file_name}
                        </p>
                        <p className="mt-1 text-xs text-muted">
                          {document.indexing_status === "evidence_only"
                            ? "仅存证据"
                            : `${document.chunk_count} 片段`}{" "}
                          · {formatDate(document.created_at)}
                        </p>
                        {document.extraction_message ? (
                          <p className="mt-1 line-clamp-2 text-xs text-danger">
                            {document.extraction_message}
                          </p>
                        ) : null}
                        {compactMeta(document).length ? (
                          <p className="mt-1 truncate text-xs text-muted">
                            {compactMeta(document).join(" / ")}
                          </p>
                        ) : null}
                      </div>
                      {canEdit ? (
                        <div className="flex shrink-0 gap-1">
                          <button
                            type="button"
                            title="查看"
                            className="grid h-7 w-7 place-items-center rounded-md border border-line text-muted hover:bg-field"
                            onClick={() => previewDocument(document)}
                          >
                            {previewLoadingId === document.document_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Eye className="h-3.5 w-3.5" />
                            )}
                          </button>
                          <button
                            type="button"
                            title="编辑标题"
                            className="grid h-7 w-7 place-items-center rounded-md border border-line text-muted hover:bg-field"
                            onClick={() => startEditing(document)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            title="删除"
                            disabled={busy}
                            className="grid h-7 w-7 place-items-center rounded-md border border-line text-danger hover:bg-orange-50 disabled:cursor-not-allowed disabled:text-muted"
                            onClick={() => deleteDocument(document)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ) : null}
                      {!canEdit ? (
                        <button
                          type="button"
                          title="查看"
                          className="grid h-7 w-7 shrink-0 place-items-center rounded-md border border-line text-muted hover:bg-field"
                          onClick={() => previewDocument(document)}
                        >
                          {previewLoadingId === document.document_id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Eye className="h-3.5 w-3.5" />
                          )}
                        </button>
                      ) : null}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {preview ? (
          <div className="rounded-md border border-line bg-white p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-xs font-semibold text-ink">
                  {preview.file_name}
                </p>
                <p className="mt-0.5 text-xs text-muted">
                  {preview.preview_type}
                  {preview.indexing_status ? ` · ${preview.indexing_status}` : ""}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                {preview.download_url ? (
                  <a
                    href={preview.download_url}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-md border border-line px-2 py-1 text-xs font-medium text-ink hover:bg-field"
                  >
                    下载
                  </a>
                ) : null}
                <button
                  type="button"
                  className="rounded-md border border-line px-2 py-1 text-xs font-medium text-muted hover:bg-field"
                  onClick={() => setPreview(null)}
                >
                  关闭
                </button>
              </div>
            </div>
            {preview.preview_type === "image" && preview.preview_url ? (
              <img
                src={preview.preview_url}
                alt={preview.file_name}
                className="max-h-80 w-full rounded-md border border-line object-contain"
              />
            ) : preview.content ? (
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-field p-3 text-xs leading-5 text-ink">
                {preview.content}
              </pre>
            ) : preview.preview_url ? (
              <a
                href={preview.preview_url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-md border border-dashed border-line bg-field px-3 py-4 text-center text-xs font-medium text-brand hover:border-brand"
              >
                打开原件预览
              </a>
            ) : (
              <div className="rounded-md border border-dashed border-line bg-field px-3 py-4 text-center text-xs text-muted">
                当前资料没有可预览内容
              </div>
            )}
            {preview.extraction_message ? (
              <p className="mt-2 text-xs leading-5 text-danger">
                {preview.extraction_message}
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted">命中片段</p>
          <div className="max-h-80 space-y-2 overflow-auto">
            {results.length === 0 ? (
              <div className="rounded-md border border-dashed border-line bg-field px-3 py-4 text-center text-xs text-muted">
                等待检索
              </div>
            ) : (
              results.map((result) => (
                <div
                  key={result.chunk_id}
                  className="rounded-md border border-line bg-white px-3 py-2"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="truncate text-xs font-medium text-ink">
                      {metadataText(result)}
                    </p>
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line bg-field px-1.5 py-0.5 text-xs text-muted">
                      <Layers3 className="h-3 w-3" />
                      {(result.score * 100).toFixed(0)}
                    </span>
                  </div>
                  <p className="line-clamp-4 text-xs leading-5 text-muted">
                    {result.content}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
