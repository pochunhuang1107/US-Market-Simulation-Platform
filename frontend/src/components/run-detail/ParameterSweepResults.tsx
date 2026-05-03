import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { formatDecimal, formatNumber, formatPct } from '../../lib/formatters';
import {
  formatParameterSummary,
  formatRankingMetricName,
  formatTradeActivity,
  formatTopVariantLabel,
  isRecord,
  toNumber,
  toStringValue
} from '../../lib/sweepVariants';
import type { RunResponse } from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

type SweepResultRow = {
  variant_id?: unknown;
  variant_name?: unknown;
  parameters?: unknown;
  total_return_pct?: unknown;
  benchmark_return_pct?: unknown;
  alpha_vs_benchmark_pct?: unknown;
  cagr_pct?: unknown;
  sharpe_ratio?: unknown;
  max_drawdown_pct?: unknown;
  trade_count?: unknown;
  trade_event_count?: unknown;
  full_exit_count?: unknown;
  buy_event_count?: unknown;
  entry_event_count?: unknown;
  add_event_count?: unknown;
  reduce_event_count?: unknown;
  config?: unknown;
  status?: unknown;
  error?: unknown;
};

const RANKING_OPTIONS = [
  { value: 'sharpe_ratio', label: 'Sharpe' },
  { value: 'total_return_pct', label: 'Total return' },
  { value: 'cagr_pct', label: 'CAGR' },
  { value: 'alpha_vs_benchmark_pct', label: 'Alpha' },
  { value: 'max_drawdown_pct', label: 'Max drawdown' }
] as const;

function getResults(summary: Record<string, unknown>): SweepResultRow[] {
  const results = summary.results;
  if (!Array.isArray(results)) return [];
  return results.filter(isRecord) as SweepResultRow[];
}

function hasMetric(results: SweepResultRow[], metric: string): boolean {
  return results.some((row) => toNumber(row[metric as keyof SweepResultRow]) !== null);
}

function normalizeRankingMetric(value: unknown, availableMetrics: string[]): string {
  const raw = toStringValue(value);
  const normalized = raw === 'sharpe' ? 'sharpe_ratio' : raw;
  if (normalized && availableMetrics.includes(normalized)) return normalized;
  return availableMetrics[0] ?? 'sharpe_ratio';
}

function rankingValue(row: SweepResultRow, metric: string): number {
  const value = toNumber(row[metric as keyof SweepResultRow]);
  if (value === null) return Number.NEGATIVE_INFINITY;
  if (metric === 'max_drawdown_pct') {
    return value <= 0 ? value : -value;
  }
  return value;
}

function sortResults(results: SweepResultRow[], metric: string): SweepResultRow[] {
  return [...results].sort((left, right) => {
    const leftSucceeded = toStringValue(left.status) === 'SUCCEEDED';
    const rightSucceeded = toStringValue(right.status) === 'SUCCEEDED';
    if (leftSucceeded !== rightSucceeded) return leftSucceeded ? -1 : 1;
    return rankingValue(right, metric) - rankingValue(left, metric);
  });
}

function getFullVariantName(row: SweepResultRow): string {
  return toStringValue(row.variant_name) ?? toStringValue(row.variant_id) ?? '—';
}

function getVariantLabel(index: number): string {
  return index === 0 ? 'Rank #1' : `Variant ${index + 1}`;
}

function getVariantId(row: SweepResultRow): string | null {
  return toStringValue(row.variant_id);
}

function formatStatus(row: SweepResultRow): string {
  const status = toStringValue(row.status);
  const error = toStringValue(row.error);
  if (status && error) return `${status}: ${error}`;
  return status ?? error ?? '—';
}

function shouldShowBenchmarkColumn(results: SweepResultRow[]): boolean {
  const values = results
    .map((row) => toNumber(row.benchmark_return_pct))
    .filter((value): value is number => value !== null);
  return new Set(values.map((value) => value.toFixed(8))).size > 1;
}

export function ParameterSweepResults({ run }: { run: RunResponse }) {
  const summary = run.summary_json ?? {};
  const results = getResults(summary);
  const availableRankingOptions = RANKING_OPTIONS.filter((option) => hasMetric(results, option.value));
  const availableRankingMetrics: string[] = availableRankingOptions.map((option) => option.value);
  const defaultRankingMetric = normalizeRankingMetric(summary.ranking_metric, availableRankingMetrics);
  const [selectedRankingMetric, setSelectedRankingMetric] = useState(defaultRankingMetric);
  const rankedResults = useMemo(
    () => sortResults(results, selectedRankingMetric),
    [results, selectedRankingMetric]
  );
  const topVariant = rankedResults[0] ?? null;
  const topVariantId = topVariant ? toStringValue(topVariant.variant_id) : null;
  const hasSweepArtifact = Boolean(run.artifact_manifest_json?.sweep_summary);
  const shouldShowArtifactNote = results.length === 0 && hasSweepArtifact;
  const hasFailures = results.some((row) => toStringValue(row.status) !== 'SUCCEEDED' || toStringValue(row.error));
  const showBenchmarkColumn = shouldShowBenchmarkColumn(results);
  const commonBenchmarkReturn = showBenchmarkColumn ? null : toNumber(results[0]?.benchmark_return_pct);
  const benchmarkSummary = showBenchmarkColumn ? 'Varies by variant' : formatPct(commonBenchmarkReturn);

  useEffect(() => {
    if (!availableRankingMetrics.includes(selectedRankingMetric)) {
      setSelectedRankingMetric(defaultRankingMetric);
    }
  }, [availableRankingMetrics, defaultRankingMetric, selectedRankingMetric]);

  return (
    <SectionCard
      title="Parameter Sweep Results"
      subtitle="Ranked variants generated from the selected parameter grid."
      actions={
        availableRankingOptions.length > 0 ? (
          <label className="flex items-center gap-2 text-sm">
            <span className="app-label text-[11px] font-semibold uppercase tracking-[0.18em]">
              Rank by
            </span>
            <select
              value={selectedRankingMetric}
              onChange={(event) => setSelectedRankingMetric(event.target.value)}
              className="app-version-input rounded-xl px-3 py-2 text-sm outline-none"
            >
              {availableRankingOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null
      }
    >
      <div className="space-y-5">
        <div className="grid gap-3 md:grid-cols-4">
          <SummaryMetric label="Ranking metric" value={formatRankingMetricName(selectedRankingMetric)} />
          <SummaryMetric label="Total variants" value={formatNumber(toNumber(summary.variant_count))} />
          <SummaryMetric
            label={formatTopVariantLabel(selectedRankingMetric)}
            value={topVariant ? formatParameterSummary(topVariant.parameters, topVariant.config) : '—'}
          />
          <SummaryMetric label="Benchmark return" value={benchmarkSummary} />
        </div>

        {topVariantId ? (
          <div className="flex flex-col gap-3 app-surface-soft rounded-2xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="app-title text-sm font-semibold">
                Review before promoting
              </div>
              <p className="app-text-muted mt-1 text-sm">
                Open the top-ranked variant to inspect metrics, changed parameters, and config.
              </p>
            </div>
            <Link
              to={`/runs/${run.id}/variants/${topVariantId}?rankingMetric=${selectedRankingMetric}`}
              className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
            >
              Review top variant
            </Link>
          </div>
        ) : null}

        {shouldShowArtifactNote ? (
          <div className="app-note rounded-2xl px-4 py-3 text-sm">
            Sweep artifacts were generated. Open sweep_summary.json from the result artifacts to inspect ranked variants.
          </div>
        ) : null}

        {results.length > 0 ? (
          <div className="app-table-frame overflow-x-auto rounded-2xl">
            <table className="w-full min-w-[900px] divide-y text-sm app-divider">
              <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
                <tr>
                  <th className="w-16 px-4 py-3">Rank</th>
                  <th className="min-w-[280px] px-4 py-3">Variant</th>
                  <th className="px-4 py-3">Total return</th>
                  {showBenchmarkColumn ? <th className="px-4 py-3">Benchmark</th> : null}
                  <th className="px-4 py-3">Alpha</th>
                  <th className="px-4 py-3">CAGR</th>
                  <th className="px-4 py-3">Sharpe</th>
                  <th className="px-4 py-3">Max drawdown</th>
                  <th className="px-4 py-3">Activity</th>
                  {hasFailures ? <th className="min-w-[180px] px-4 py-3">Status</th> : null}
                  <th className="w-28 px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody className="app-table-body divide-y app-divider">
                {rankedResults.map((row, index) => {
                  const variantId = getVariantId(row);
                  return (
                    <tr key={`${getFullVariantName(row)}-${index}`} className="app-row-hover align-top">
                      <td className="px-4 py-3 font-medium">{index + 1}</td>
                      <td className="px-4 py-3">
                        <div className="app-title whitespace-nowrap font-medium">
                          {getVariantLabel(index)}
                        </div>
                        <div className="app-text-muted mt-1 max-w-[340px] text-xs">
                          {formatParameterSummary(row.parameters, row.config)}
                        </div>
                        <div className="app-text-soft mt-1 max-w-[300px] truncate text-xs" title={getFullVariantName(row)}>
                          {getFullVariantName(row)}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">{formatPct(toNumber(row.total_return_pct))}</td>
                      {showBenchmarkColumn ? (
                        <td className="whitespace-nowrap px-4 py-3">{formatPct(toNumber(row.benchmark_return_pct))}</td>
                      ) : null}
                      <td className="whitespace-nowrap px-4 py-3">{formatPct(toNumber(row.alpha_vs_benchmark_pct))}</td>
                      <td className="whitespace-nowrap px-4 py-3">{formatPct(toNumber(row.cagr_pct))}</td>
                      <td className="whitespace-nowrap px-4 py-3">{formatDecimal(toNumber(row.sharpe_ratio))}</td>
                      <td className="whitespace-nowrap px-4 py-3">{formatPct(toNumber(row.max_drawdown_pct))}</td>
                      <td className="whitespace-nowrap px-4 py-3">{formatTradeActivity(row)}</td>
                      {hasFailures ? (
                        <td className="max-w-[240px] px-4 py-3">
                          <span className="line-clamp-2" title={formatStatus(row)}>
                            {formatStatus(row)}
                          </span>
                        </td>
                      ) : null}
                      <td className="whitespace-nowrap px-4 py-3">
                        {variantId ? (
                          <Link
                            to={`/runs/${run.id}/variants/${variantId}?rankingMetric=${selectedRankingMetric}`}
                            className="app-button-secondary rounded-xl px-3 py-1.5 text-xs font-semibold transition"
                          >
                            Review
                          </Link>
                        ) : (
                          <span className="app-button-secondary rounded-xl px-3 py-1.5 text-xs font-semibold opacity-60">
                            Review
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : shouldShowArtifactNote ? null : (
          <div className="app-note rounded-2xl px-4 py-3 text-sm">
            No ranked variants were available in this result summary.
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="app-surface-soft rounded-2xl border px-4 py-3">
      <div className="app-label text-[11px] font-semibold uppercase tracking-[0.2em]">
        {label}
      </div>
      <div className="app-title mt-2 text-sm font-semibold">{value}</div>
    </div>
  );
}
