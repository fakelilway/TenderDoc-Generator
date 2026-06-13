import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Search,
  ShieldCheck
} from "lucide-react";
import type { ReviewFinding, ReviewReport, ReviewStatus } from "@/lib/types";

const ruleLabels: Record<string, string> = {
  project_manager_certificate: "项目经理证书",
  safety_production_license: "安全生产许可证",
  bid_bond: "投标保证金",
  pricing_manual_confirmation: "报价人工确认",
  general_completeness: "完整性审查"
};

const severityLabels: Record<string, string> = {
  high: "高风险",
  medium: "中风险",
  low: "低风险"
};

function statusTone(status: ReviewStatus) {
  if (status === "pass") {
    return {
      icon: CheckCircle2,
      label: "通过",
      className: "border-green-200 bg-green-50 text-ok"
    };
  }
  if (status === "warning") {
    return {
      icon: AlertTriangle,
      label: "警告",
      className: "border-amber-200 bg-amber-50 text-warn"
    };
  }
  return {
    icon: CircleAlert,
    label: "失败",
    className: "border-orange-200 bg-orange-50 text-danger"
  };
}

function findingTitle(finding: ReviewFinding) {
  return (
    finding.field?.trim() ||
    ruleLabels[finding.rule] ||
    finding.rule.replaceAll("_", " ")
  );
}

function severityLabel(severity: string) {
  return severityLabels[severity] || severity;
}

export function RiskPanel({
  report,
  activeLine,
  onSelect
}: {
  report: ReviewReport | null;
  activeLine: number | null;
  onSelect: (line: number | null) => void;
}) {
  const findings = report?.findings ?? [];

  return (
    <section className="ios-panel flex min-h-[320px] flex-col rounded-[26px] border">
      <div className="flex h-14 items-center justify-between border-b border-black/[0.06] px-4">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-[#34c759]/10 text-[#34c759]">
            <ShieldCheck className="h-4 w-4" />
          </span>
          <h2 className="text-sm font-semibold text-[#1d1d1f]">审查报告</h2>
        </div>
        {report ? (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-ok">{report.pass_count}</span>
            <span className="text-danger">{report.fail_count}</span>
            <span className="text-warn">{report.warning_count}</span>
          </div>
        ) : null}
      </div>

      <div className="flex-1 overflow-auto p-4">
        {findings.length === 0 ? (
          <div className="grid h-full min-h-96 place-items-center rounded-lg border border-dashed border-line bg-field text-sm text-muted">
            等待审查报告
          </div>
        ) : (
          <div className="space-y-3">
            {findings.map((finding, index) => {
              const tone = statusTone(finding.status);
              const Icon = tone.icon;
              const lineNumber = finding.location?.line_number ?? null;
              const selected = lineNumber !== null && lineNumber === activeLine;

              return (
                <button
                  key={`${finding.rule}-${index}`}
                  type="button"
                  className={[
                    "w-full rounded-lg border p-3 text-left transition",
                    selected
                      ? "border-danger bg-orange-50"
                      : "border-line bg-white hover:border-brand hover:bg-blue-50"
                  ].join(" ")}
                  onClick={() => onSelect(lineNumber)}
                >
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-ink">
                        {findingTitle(finding)}
                      </p>
                      <p className="mt-1 text-xs text-muted">
                        {severityLabel(finding.severity)}
                      </p>
                    </div>
                    <span
                      className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${tone.className}`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {tone.label}
                    </span>
                  </div>
                  <p className="line-clamp-3 text-xs leading-5 text-muted">
                    {finding.suggestion || finding.evidence}
                  </p>
                  {lineNumber ? (
                    <p className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-brand">
                      <Search className="h-3.5 w-3.5" />
                      第 {lineNumber} 行
                    </p>
                  ) : null}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
