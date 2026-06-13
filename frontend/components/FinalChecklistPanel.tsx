"use client";

import type { FinalChecklist, FinalVersion } from "@/lib/types";

type Props = {
  checklist: FinalChecklist | null;
  versions: FinalVersion[];
};

export function FinalChecklistPanel({ checklist, versions }: Props) {
  if (!checklist && versions.length === 0) {
    return null;
  }

  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <h2 className="text-sm font-semibold text-ink">终审清单</h2>
      <div className="mt-3 space-y-3 text-xs text-muted">
        <Metric
          label="废标响应"
          value={checklist?.invalid_bid_responses?.length ?? 0}
        />
        <Metric
          label="人工确认点"
          value={checklist?.manual_confirmation_points?.length ?? 0}
        />
        <Metric
          label="报价填写点"
          value={checklist?.pricing_manual_fields?.length ?? 0}
        />
        <Metric label="附件清单" value={checklist?.attachment_list?.length ?? 0} />
      </div>
      {versions.length ? (
        <div className="mt-4 border-t border-black/[0.06] pt-3">
          <h3 className="text-xs font-semibold text-ink">版本</h3>
          <div className="mt-2 space-y-1 text-xs text-muted">
            {versions.map((version) => (
              <div key={version.version}>v{version.version}</div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between rounded-[16px] bg-white/56 px-3 py-2">
      <span>{label}</span>
      <span className="font-semibold text-ink">{value}</span>
    </div>
  );
}
