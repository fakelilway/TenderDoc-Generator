"use client";

import { Search, Save } from "lucide-react";
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
  onSave: () => void;
};

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
  onToggle,
  onSave
}: Props) {
  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">资料选择</h2>
        <button
          type="button"
          disabled={busy || selectedIds.length === 0}
          className="inline-flex h-8 items-center gap-2 rounded-md bg-ok px-3 text-xs font-semibold text-white hover:bg-green-700 disabled:bg-green-300"
          onClick={onSave}
        >
          <Save className="h-4 w-4" />
          采用
        </button>
      </div>
      <div className="mt-3 grid gap-2">
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          className="h-9 rounded-md border border-line bg-field px-3 text-sm text-ink outline-none focus:border-brand"
        />
        <div className="grid grid-cols-2 gap-2">
          <input
            value={projectType}
            placeholder="项目类型"
            onChange={(event) => onProjectTypeChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={documentType}
            placeholder="细分类型"
            onChange={(event) => onDocumentTypeChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={documentCategory}
            placeholder="资料类别"
            onChange={(event) => onDocumentCategoryChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={specialty}
            placeholder="专业"
            onChange={(event) => onSpecialtyChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={volume}
            placeholder="所属卷册"
            onChange={(event) => onVolumeChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={region}
            placeholder="地区"
            onChange={(event) => onRegionChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={certificateType}
            placeholder="证件/证明"
            onChange={(event) => onCertificateTypeChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={usageScope}
            placeholder="用途范围"
            onChange={(event) => onUsageScopeChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={verifiedStatus}
            placeholder="核验状态"
            onChange={(event) => onVerifiedStatusChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
          <input
            value={tagText}
            placeholder="标签"
            onChange={(event) => onTagTextChange(event.target.value)}
            className="h-9 rounded-md border border-line bg-field px-3 text-xs text-ink outline-none focus:border-brand"
          />
        </div>
        <button
          type="button"
          disabled={busy || !query.trim()}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-line bg-white text-sm font-medium text-ink hover:bg-field disabled:text-muted"
          onClick={onSearch}
        >
          <Search className="h-4 w-4" />
          检索
        </button>
      </div>
      <div className="mt-3 max-h-72 space-y-2 overflow-auto">
        {results.map((result) => (
          <label
            key={result.chunk_id}
            className="block rounded-md border border-line bg-field p-3 text-xs text-ink"
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
          已采用 {references.length} 个资料片段
        </div>
      ) : null}
    </section>
  );
}
