import { formatDecimal, formatNumber, formatPct } from '../../lib/formatters';
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
  status?: unknown;
  error?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function toStringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function getResults(summary: Record<string, unknown>): SweepResultRow[] {
  const results = summary.results;
  if (!Array.isArray(results)) return [];
  return results.filter(isRecord) as SweepResultRow[];
}

function formatMetricName(value: unknown): string {
  const raw = toStringValue(value);
  if (!raw) return '—';
  return raw.replace(/_/g, ' ');
}

function getFullVariantName(row: SweepResultRow): string {
  return toStringValue(row.variant_name) ?? toStringValue(row.variant_id) ?? '—';
}

function getVariantLabel(index: number): string {
  return index === 0 ? 'Best variant' : `Variant ${index + 1}`;
}

const PARAMETER_LABELS: Record<string, string> = {
  'entry_rule.slow_window': 'Entry slow window',
  'exit_rule.slow_window': 'Exit slow window',
  'entry_rule.fast_window': 'Entry fast window',
  'exit_rule.fast_window': 'Exit fast window',
  'entry_rule.threshold': 'Entry threshold',
  'exit_rule.threshold': 'Exit threshold',
  'entry_rule.lookback': 'Entry lookback',
  'exit_rule.lookback': 'Exit lookback',
  'risk.stop_loss_pct': 'Stop loss',
  'risk.take_profit_pct': 'Take profit',
  'risk.cooldown_bars': 'Cooldown bars',
  'allocation.entry_value': 'Entry allocation',
  'allocation.max_position_pct': 'Max position'
};

function formatParameterValue(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

function formatParameterLabel(path: string): string {
  return PARAMETER_LABELS[path] ?? path;
}

function formatStatus(row: SweepResultRow): string {
  const status = toStringValue(row.status);
  const error = toStringValue(row.error);
  if (status && error) return `${status}: ${error}`;
  return status ?? error ?? '—';
}

export function ParameterSweepResults({ run }: { run: RunResponse }) {
  const summary = run.summary_json ?? {};
  const results = getResults(summary);
  const bestVariant = isRecord(summary.best_variant) ? summary.best_variant : null;
  const hasSweepArtifact = Boolean(run.artifact_manifest_json?.sweep_summary);
  const shouldShowArtifactNote = results.length === 0 && hasSweepArtifact;
  const hasFailures = results.some((row) => toStringValue(row.status) !== 'SUCCEEDED' || toStringValue(row.error));

  return (
    <SectionCard
      title="Parameter Sweep Results"
      subtitle="Ranked variants generated from the selected parameter grid."
    >
      <div className="space-y-5">
        <div className="grid gap-3 md:grid-cols-3">
          <SummaryMetric label="Ranking metric" value={formatMetricName(summary.ranking_metric)} />
          <SummaryMetric label="Total variants" value={formatNumber(toNumber(summary.variant_count))} />
          <SummaryMetric
            label="Best variant"
            value={bestVariant ? getFullVariantName(bestVariant) : '—'}
          />
        </div>

        {shouldShowArtifactNote ? (
          <div className="app-note rounded-2xl px-4 py-3 text-sm">
            Sweep artifacts were generated. Open sweep_summary.json from the run artifacts to inspect ranked variants.
          </div>
        ) : null}

        {results.length > 0 ? (
          <div className="app-table-frame overflow-auto rounded-2xl">
            <table className="min-w-[980px] divide-y text-sm app-divider">
              <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
                <tr>
                  <th className="px-3 py-3">Rank</th>
                  <th className="px-3 py-3">Variant</th>
                  <th className="px-3 py-3">Parameters</th>
                  <th className="px-3 py-3">Total return</th>
                  <th className="px-3 py-3">Benchmark</th>
                  <th className="px-3 py-3">Alpha</th>
                  <th className="px-3 py-3">CAGR</th>
                  <th className="px-3 py-3">Sharpe</th>
                  <th className="px-3 py-3">Max drawdown</th>
                  <th className="px-3 py-3">Trades</th>
                  {hasFailures ? <th className="px-3 py-3">Status</th> : null}
                </tr>
              </thead>
              <tbody className="app-table-body divide-y app-divider">
                {results.map((row, index) => (
                  <tr key={`${getFullVariantName(row)}-${index}`} className="app-row-hover align-top">
                    <td className="px-3 py-2.5 font-medium">{index + 1}</td>
                    <td className="px-3 py-2.5">
                      <div className="app-title whitespace-nowrap font-medium">
                        {getVariantLabel(index)}
                      </div>
                      <div className="app-text-soft mt-1 max-w-[180px] truncate text-xs" title={getFullVariantName(row)}>
                        {getFullVariantName(row)}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <ParameterList value={row.parameters} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5">{formatPct(toNumber(row.total_return_pct))}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{formatPct(toNumber(row.benchmark_return_pct))}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{formatPct(toNumber(row.alpha_vs_benchmark_pct))}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{formatPct(toNumber(row.cagr_pct))}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{formatDecimal(toNumber(row.sharpe_ratio))}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{formatPct(toNumber(row.max_drawdown_pct))}</td>
                    <td className="whitespace-nowrap px-3 py-2.5">{formatNumber(toNumber(row.trade_count))}</td>
                    {hasFailures ? (
                      <td className="max-w-[220px] px-3 py-2.5">
                        <span className="line-clamp-2" title={formatStatus(row)}>
                          {formatStatus(row)}
                        </span>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : shouldShowArtifactNote ? null : (
          <div className="app-note rounded-2xl px-4 py-3 text-sm">
            No ranked variants were available in this run summary.
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function ParameterList({ value }: { value: unknown }) {
  if (!isRecord(value)) return <span>—</span>;

  const entries = Object.entries(value);
  if (entries.length === 0) return <span>—</span>;

  return (
    <div className="flex max-w-[260px] flex-col gap-1.5">
      {entries.map(([path, parameterValue]) => (
        <div key={path} className="leading-5">
          <span className="app-title font-medium">{formatParameterLabel(path)}:</span>{' '}
          <span className="app-text-muted">{formatParameterValue(parameterValue)}</span>
        </div>
      ))}
    </div>
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
