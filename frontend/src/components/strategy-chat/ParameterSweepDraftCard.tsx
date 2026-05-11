import { useMemo, useState } from 'react';

import { formatParameterLabel } from '../../lib/sweepVariants';
import { explainRule } from '../../lib/ruleSummaries';
import type { StrategyBuilderGenerateResponse } from '../../types/api';

function prettifyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return '{}';
  }
}

function titleCase(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatMetric(value: string): string {
  return titleCase(value);
}

function formatGridValue(path: string, value: unknown): string {
  if (typeof value === 'number') {
    if (path.includes('_pct') || path.includes('_fraction')) return `${(value * 100).toFixed(1)}%`;
    return Number.isInteger(value) ? `${value}` : `${value}`;
  }
  if (value === null) return 'None';
  return String(value);
}

function InfoPill({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="app-home-draft-panel rounded-2xl px-4 py-3">
      <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">{label}</div>
      <div className="app-title mt-1 text-sm">{value ?? '-'}</div>
    </div>
  );
}

export function ParameterSweepDraftCard({
  draft,
  onRun,
  isLatestDraft = true,
  isRunning = false,
  runError = null
}: {
  draft: StrategyBuilderGenerateResponse;
  onRun: () => void;
  isLatestDraft?: boolean;
  isRunning?: boolean;
  runError?: string | null;
}) {
  const [showJson, setShowJson] = useState(false);
  const sweep = draft.sweep_draft;

  const viewModel = useMemo(() => {
    const baseConfig = sweep?.base_config ?? {};
    const grid = sweep?.grid ?? {};
    const gridRows = Object.entries(grid).map(([path, values]) => ({
      path,
      label: formatParameterLabel(path, baseConfig),
      values: values.map((value) => formatGridValue(path, value)).join(', ')
    }));

    return {
      title: sweep?.title ?? 'Parameter Sweep Draft',
      symbol: typeof baseConfig.tradable_symbol === 'string' ? baseConfig.tradable_symbol : '-',
      benchmark: typeof baseConfig.benchmark_symbol === 'string' ? baseConfig.benchmark_symbol : '-',
      startDate: typeof baseConfig.start_date === 'string' ? baseConfig.start_date : '-',
      endDate: typeof baseConfig.end_date === 'string' ? baseConfig.end_date : '-',
      rankingMetric: sweep?.ranking_metric ? formatMetric(sweep.ranking_metric) : '-',
      variantCount: sweep?.variant_count ?? '-',
      maxVariants: sweep?.max_variants ?? '-',
      entryRule: explainRule(baseConfig.entry_rule, { tradableSymbol: baseConfig.tradable_symbol }),
      exitRule: explainRule(baseConfig.exit_rule, { tradableSymbol: baseConfig.tradable_symbol }),
      gridRows,
      json: {
        base_config: baseConfig,
        grid,
        ranking_metric: sweep?.ranking_metric,
        max_variants: sweep?.max_variants
      }
    };
  }, [sweep]);

  return (
    <div className="app-card app-home-draft-card app-shadow rounded-[32px] border p-5">
      <div className="app-divider flex flex-col gap-4 border-b pb-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="app-chip-info rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]">
              Parameter Sweep Draft
            </span>
            <span className="app-chip-success rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]">
              Ready to run
            </span>
          </div>
          <div>
            <h2 className="app-title text-lg font-semibold tracking-tight">{viewModel.title}</h2>
            <p className="app-text-muted mt-2 whitespace-pre-wrap text-sm leading-6">
              {draft.summary ?? sweep?.summary}
            </p>
          </div>
        </div>

        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap sm:items-start sm:justify-end lg:self-start">
          <button
            type="button"
            onClick={() => setShowJson((value) => !value)}
            className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-semibold leading-5 transition sm:whitespace-nowrap"
          >
            {showJson ? 'Hide JSON' : 'Show JSON'}
          </button>
          {isLatestDraft ? (
            <button
              type="button"
              onClick={onRun}
              disabled={isRunning}
              className="app-button-primary rounded-2xl px-4 py-2 text-sm font-semibold leading-5 transition disabled:cursor-not-allowed disabled:opacity-60 sm:whitespace-nowrap"
            >
              {isRunning ? 'Running...' : 'Run Parameter Sweep'}
            </button>
          ) : (
            <div className="app-surface-soft max-w-[11.5rem] rounded-2xl border px-3 py-2 text-sm font-medium leading-5 app-text-muted">
              Superseded by newer draft
            </div>
          )}
        </div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <InfoPill label="Symbol" value={viewModel.symbol} />
        <InfoPill label="Benchmark" value={viewModel.benchmark} />
        <InfoPill label="Start Date" value={viewModel.startDate} />
        <InfoPill label="End Date" value={viewModel.endDate} />
        <InfoPill label="Ranking Metric" value={viewModel.rankingMetric} />
        <InfoPill label="Variants" value={`${viewModel.variantCount} / ${viewModel.maxVariants}`} />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <section className="app-home-draft-section rounded-3xl p-5">
          <div className="app-accent text-[11px] font-semibold uppercase tracking-[0.24em]">Parameter grid</div>
          <h3 className="app-title mt-1 text-sm font-semibold">Values to test</h3>
          <div className="mt-3 space-y-3">
            {viewModel.gridRows.map((row) => (
              <div key={row.path} className="app-home-draft-panel rounded-2xl p-4">
                <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">{row.label}</div>
                <div className="app-title mt-2 text-sm leading-6">{row.values}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="app-home-draft-section rounded-3xl p-5">
          <div className="app-accent text-[11px] font-semibold uppercase tracking-[0.24em]">Base strategy</div>
          <h3 className="app-title mt-1 text-sm font-semibold">Signal logic</h3>
          <div className="mt-3 space-y-3 text-sm">
            <div className="app-home-draft-panel rounded-2xl p-4">
              <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">Entry</div>
              <div className="app-title mt-2 leading-6">{viewModel.entryRule}</div>
            </div>
            <div className="app-home-draft-panel rounded-2xl p-4">
              <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">Exit</div>
              <div className="app-title mt-2 leading-6">{viewModel.exitRule}</div>
            </div>
          </div>
        </section>
      </div>

      {draft.warnings.length > 0 ? (
        <div className="app-alert-warning mt-4 rounded-3xl p-5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em]">Warnings</div>
          <ul className="mt-3 space-y-2 text-sm">
            {draft.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {runError ? <div className="app-alert-error mt-4 rounded-2xl px-4 py-3 text-sm">{runError}</div> : null}

      {showJson ? (
        <div className="app-home-json-panel mt-4 rounded-3xl p-5">
          <div className="app-label mb-3 text-[11px] font-semibold uppercase tracking-[0.22em]">Sweep Request JSON</div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6">{prettifyJson(viewModel.json)}</pre>
        </div>
      ) : null}
    </div>
  );
}
