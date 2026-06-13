"use client";

import { BarChart3, Calculator, Loader2, Search, Table2 } from "lucide-react";
import type {
  PricingStrategy,
  PricingStrategyReport,
  ResponseMatrix,
  ScorePrediction
} from "@/lib/types";

type Props = {
  pricingStrategy: PricingStrategy | null;
  pricingReport: PricingStrategyReport | null;
  scorePrediction: ScorePrediction | null;
  responseMatrix: ResponseMatrix | null;
  busy: boolean;
  disabled: boolean;
  onBuildPricing: () => void;
  onBuildScore: () => void;
  onBuildMatrix: () => void;
  onSelectLine: (line: number | null) => void;
};

export function StrategyPanel({
  pricingStrategy,
  pricingReport,
  scorePrediction,
  responseMatrix,
  busy,
  disabled,
  onBuildPricing,
  onBuildScore,
  onBuildMatrix,
  onSelectLine
}: Props) {
  return (
    <section className="ios-panel rounded-[26px] border p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-[#1d1d1f]">策略与评分</h2>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-brand" /> : null}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <ActionButton
          icon="pricing"
          label="报价"
          disabled={busy || disabled}
          onClick={onBuildPricing}
        />
        <ActionButton
          icon="score"
          label="评分"
          disabled={busy || disabled}
          onClick={onBuildScore}
        />
        <ActionButton
          icon="matrix"
          label="矩阵"
          disabled={busy || disabled}
          onClick={onBuildMatrix}
        />
      </div>

      {pricingReport || pricingStrategy ? (
        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-ink">
            <Calculator className="h-3.5 w-3.5 text-brand" />
            报价策略
          </div>
          <Metric label="人工填写项" value={pricingStrategy?.manual_fields.length ?? 0} />
          <Metric label="付款条件" value={pricingStrategy?.payment_terms.length ?? 0} />
          <Metric
            label="担保约束"
            value={pricingStrategy?.guarantee_requirements.length ?? 0}
          />
          <TextList items={pricingReport?.risk_warnings ?? []} />
        </div>
      ) : null}

      {scorePrediction ? (
        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-ink">
            <BarChart3 className="h-3.5 w-3.5 text-ok" />
            评分预测
          </div>
          <div className="rounded-md bg-field px-3 py-2 text-xs text-muted">
            <div className="flex items-center justify-between">
              <span>预测总分</span>
              <span className="font-semibold text-ink">
                {scorePrediction.predicted_total_score}/
                {scorePrediction.total_max_score}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span>中标概率</span>
              <span className="font-semibold text-ink">
                {scorePrediction.win_probability == null
                  ? "-"
                  : `${Math.round(scorePrediction.win_probability * 100)}%`}
              </span>
            </div>
          </div>
          <p className="mt-2 text-xs leading-5 text-muted">
            {scorePrediction.win_probability_rationale}
          </p>
          <TextList items={scorePrediction.weaknesses.slice(0, 3)} />
        </div>
      ) : null}

      {responseMatrix ? (
        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-ink">
            <Table2 className="h-3.5 w-3.5 text-warn" />
            响应矩阵
          </div>
          <Metric label="矩阵行" value={responseMatrix.rows.length} />
          <Metric
            label="废标覆盖"
            value={responseMatrix.invalid_bid_coverage_count}
            suffix={`/${responseMatrix.total_invalid_bid_count}`}
          />
          <div className="mt-2 max-h-56 space-y-2 overflow-auto">
            {responseMatrix.rows.slice(0, 8).map((row, index) => {
              const line = row.response_location?.line_number ?? null;
              return (
                <button
                  key={`${row.requirement_type}-${row.requirement_title}-${index}`}
                  type="button"
                  className="w-full rounded-md border border-line bg-white px-3 py-2 text-left text-xs hover:border-brand hover:bg-blue-50"
                  onClick={() => onSelectLine(line)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="line-clamp-1 font-medium text-ink">
                      {row.requirement_title}
                    </span>
                    <span className="shrink-0 text-muted">{row.review_status}</span>
                  </div>
                  {line ? (
                    <span className="mt-1 inline-flex items-center gap-1 text-brand">
                      <Search className="h-3 w-3" />
                      line {line}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ActionButton({
  icon,
  label,
  disabled,
  onClick
}: {
  icon: "pricing" | "score" | "matrix";
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  const Icon =
    icon === "pricing" ? Calculator : icon === "score" ? BarChart3 : Table2;
  return (
    <button
      type="button"
      disabled={disabled}
      className="inline-flex h-9 items-center justify-center gap-1 rounded-md border border-line bg-white px-2 text-xs font-medium text-ink hover:bg-field disabled:cursor-not-allowed disabled:text-muted"
      onClick={onClick}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

function Metric({
  label,
  value,
  suffix = ""
}: {
  label: string;
  value: number;
  suffix?: string;
}) {
  return (
    <div className="mt-2 flex items-center justify-between rounded-md bg-field px-3 py-2 text-xs text-muted">
      <span>{label}</span>
      <span className="font-semibold text-ink">
        {value}
        {suffix}
      </span>
    </div>
  );
}

function TextList({ items }: { items: string[] }) {
  if (!items.length) {
    return null;
  }
  return (
    <ul className="mt-2 space-y-1 text-xs leading-5 text-muted">
      {items.slice(0, 4).map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
