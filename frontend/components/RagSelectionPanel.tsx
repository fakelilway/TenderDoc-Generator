"use client";

import { ChevronDown, Search } from "lucide-react";
import type { KnowledgeSearchResult, RagReference } from "@/lib/types";

type Props = {
  query: string;
  projectType: string;
  documentType: string;
  documentCategory: string;
  specialty: string;
  volume: string;
  region: string;
  certificateType: string;
  usageScope: string;
  verifiedStatus: string;
  tagText: string;
  availableTags?: string[];
  results: KnowledgeSearchResult[];
  selectedIds: number[];
  references: RagReference[];
  busy: boolean;
  onQueryChange: (value: string) => void;
  onProjectTypeChange: (value: string) => void;
  onDocumentTypeChange: (value: string) => void;
  onDocumentCategoryChange: (value: string) => void;
  onSpecialtyChange: (value: string) => void;
  onVolumeChange: (value: string) => void;
  onRegionChange: (value: string) => void;
  onCertificateTypeChange: (value: string) => void;
  onUsageScopeChange: (value: string) => void;
  onVerifiedStatusChange: (value: string) => void;
  onTagTextChange: (value: string) => void;
  onSearch: () => void;
  onToggle: (chunkId: number) => void;
};

function splitTags(value: string) {
  return value
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function RagSelectionPanel({
  query,
  projectType,
  documentType,
  documentCategory,
  specialty,
  volume,
  region,
  certificateType,
  usageScope,
  verifiedStatus,
  tagText,
  availableTags = [],
  results,
  selectedIds,
  references,
  busy,
  onQueryChange,
  onProjectTypeChange,
  onDocumentTypeChange,
  onDocumentCategoryChange,
  onSpecialtyChange,
  onVolumeChange,
  onRegionChange,
  onCertificateTypeChange,
  onUsageScopeChange,
  onVerifiedStatusChange,
  onTagTextChange,
  onSearch,
  onToggle
}: Props) {
  const activeTags = splitTags(tagText);

  function toggleTag(tag: string) {
    const next = activeTags.includes(tag)
      ? activeTags.filter((item) => item !== tag)
      : [...activeTags, tag];
    onTagTextChange(next.join(", "));
  }

  const advancedFilters: Array<[string, string, (value: string) => void]> = [
    ["项目类型", projectType, onProjectTypeChange],
    ["细分类型", documentType, onDocumentTypeChange],
    ["资料类别", documentCategory, onDocumentCategoryChange],
    ["专业", specialty, onSpecialtyChange],
    ["所属卷册", volume, onVolumeChange],
    ["地区", region, onRegionChange],
    ["证件/证明", certificateType, onCertificateTypeChange],
    ["用途范围", usageScope, onUsageScopeChange],
    ["核验状态", verifiedStatus, onVerifiedStatusChange]
  ];

  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">资料选择（可选）</h2>
        {selectedIds.length > 0 ? (
          <span className="rounded-md border border-green-200 bg-green-50 px-2 py-1 text-xs font-medium text-ok">
            已采用 {selectedIds.length} 个片段
          </span>
        ) : null}
      </div>

      <p className="mt-2 rounded-md border border-line bg-field px-3 py-2 text-xs leading-5 text-muted">
        不勾选时，生成会<span className="font-medium text-ink">自动从知识库检索</span>最相关的资料；
        勾选后，生成<span className="font-medium text-ink">只使用勾选的资料</span>。
        勾选即生效，无需另外保存。
      </p>

      <div className="mt-3 grid gap-2">
        <div className="flex gap-2">
          <input
            value={query}
            placeholder="输入关键词，例如：施工方案、营业执照"
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && query.trim() && !busy) {
                onSearch();
              }
            }}
            className="h-9 min-w-0 flex-1 rounded-md border border-line bg-field px-3 text-sm text-ink outline-none focus:border-brand"
          />
          <button
            type="button"
            disabled={busy || !query.trim()}
            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink hover:bg-field disabled:text-muted"
            onClick={onSearch}
          >
            <Search className="h-4 w-4" />
            检索
          </button>
        </div>

        {availableTags.length ? (
          <div className="flex flex-wrap gap-1.5">
            {availableTags.map((tag) => {
              const active = activeTags.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  onClick={() => toggleTag(tag)}
                  className={[
                    "rounded-full border px-2.5 py-1 text-xs transition-colors",
                    active
                      ? "border-brand bg-blue-50 font-medium text-brand"
                      : "border-line bg-field text-muted hover:border-brand hover:text-ink"
                  ].join(" ")}
                >
                  {tag}
                </button>
              );
            })}
          </div>
        ) : null}

        <details className="group rounded-md border border-line bg-field">
          <summary className="flex cursor-pointer select-none items-center justify-between px-3 py-2 text-xs font-medium text-muted">
            高级筛选
            <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
          </summary>
          <div className="grid grid-cols-2 gap-2 px-3 pb-3">
            <p className="col-span-2 text-xs leading-5 text-muted">
              以下条件需与资料入库时填写的属性完全一致，通常留空即可。
            </p>
            {advancedFilters.map(([label, value, onChange]) => (
              <input
                key={label}
                value={value}
                placeholder={label}
                onChange={(event) => onChange(event.target.value)}
                className="h-9 rounded-md border border-line bg-white px-3 text-xs text-ink outline-none focus:border-brand"
              />
            ))}
          </div>
        </details>
      </div>

      <div className="mt-3 max-h-72 space-y-2 overflow-auto">
        {busy ? (
          <div className="rounded-md border border-line bg-field p-3 text-xs text-muted">
            正在检索资料...
          </div>
        ) : null}
        {!busy && query.trim() && results.length === 0 ? (
          <div className="rounded-md border border-line bg-field p-3 text-xs text-muted">
            没有检索到资料。可以先清空筛选条件再试；图片/证件资料需要重新上传或重新索引后才会进入资料选择检索。
          </div>
        ) : null}
        {results.map((result) => (
          <label
            key={result.chunk_id}
            className="block cursor-pointer rounded-md border border-line bg-field p-3 text-xs text-ink hover:border-brand"
          >
            <div className="flex items-center gap-2 font-medium">
              <input
                type="checkbox"
                checked={selectedIds.includes(result.chunk_id)}
                onChange={() => onToggle(result.chunk_id)}
              />
              <span>{String(result.metadata.file_name ?? result.document_id ?? result.chunk_id)}</span>
            </div>
            <p className="mt-2 line-clamp-4 text-muted">{result.content}</p>
          </label>
        ))}
      </div>
      {references.length ? (
        <div className="mt-3 rounded-md border border-line bg-field p-3 text-xs text-muted">
          已采用 {references.length} 个资料片段，生成时只使用这些资料。
        </div>
      ) : null}
    </section>
  );
}
