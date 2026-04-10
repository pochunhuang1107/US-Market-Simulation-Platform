import { useMemo, useState } from 'react';

import type { StrategyBuilderGenerateResponse } from '../../types/api';

function prettifyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return '{}';
  }
}

function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-sm text-slate-100">{value ?? '—'}</div>
    </div>
  );
}

function BulletList({
  title,
  items,
  tone = 'default'
}: {
  title: string;
  items: string[];
  tone?: 'default' | 'warning';
}) {
  const toneClasses =
    tone === 'warning'
      ? 'border-amber-900/60 bg-amber-950/20 text-amber-100'
      : 'border-slate-800 bg-slate-950/60 text-slate-100';

  const bulletTone = tone === 'warning' ? 'text-amber-300' : 'text-cyan-300';

  return (
    <section className={`rounded-2xl border px-4 py-4 ${toneClasses}`}>
      <div className="text-sm font-semibold">{title}</div>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-slate-400">None.</p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className="flex gap-2">
              <span className={bulletTone}>•</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function StrategyDraftCard({
  draft,
  onRun,
  isRunning = false,
  runError = null
}: {
  draft: StrategyBuilderGenerateResponse;
  onRun: () => void;
  isRunning?: boolean;
  runError?: string | null;
}) {
  const [showConfig, setShowConfig] = useState(false);

  const stats = useMemo(() => {
    const config = draft.config ?? {};
    const risk = (config.risk as Record<string, unknown> | undefined) ?? {};
    return {
      name: typeof config.name === 'string' ? config.name : 'generated-strategy',
      tradableSymbol:
        typeof config.tradable_symbol === 'string' ? config.tradable_symbol : '—',
      benchmarkSymbol:
        typeof config.benchmark_symbol === 'string' ? config.benchmark_symbol : '—',
      startDate: typeof config.start_date === 'string' ? config.start_date : '—',
      endDate: typeof config.end_date === 'string' ? config.end_date : '—',
      stopLoss:
        typeof risk.stop_loss_pct === 'number' ? `${(risk.stop_loss_pct * 100).toFixed(1)}%` : '—',
      takeProfit:
        typeof risk.take_profit_pct === 'number' ? `${(risk.take_profit_pct * 100).toFixed(1)}%` : '—'
    };
  }, [draft.config]);

  return (
    <div className="space-y-4">
      <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">
              Parsed strategy draft
            </div>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-200">
              {draft.summary}
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setShowConfig((value) => !value)}
              className="rounded-2xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-900"
            >
              {showConfig ? 'Hide Config' : 'Show Config'}
            </button>
            <button
              type="button"
              onClick={onRun}
              disabled={isRunning}
              className="rounded-2xl bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isRunning ? 'Running...' : 'Run Simulation'}
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <InfoRow label="Strategy Name" value={stats.name} />
          <InfoRow label="Tradable Symbol" value={stats.tradableSymbol} />
          <InfoRow label="Benchmark" value={stats.benchmarkSymbol} />
          <InfoRow label="Start Date" value={stats.startDate} />
          <InfoRow label="End Date" value={stats.endDate} />
          <InfoRow label="Stop Loss / Take Profit" value={`${stats.stopLoss} / ${stats.takeProfit}`} />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <BulletList title="Changes" items={draft.changes ?? []} />
          <BulletList title="Warnings" items={draft.warnings ?? []} tone="warning" />
        </div>

        {runError ? (
          <div className="mt-4 rounded-2xl border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
            {runError}
          </div>
        ) : null}

        {showConfig ? (
          <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950 px-4 py-4">
            <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
              Canonical Strategy V2 JSON
            </div>
            <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6 text-slate-200">
              {prettifyJson(draft.config)}
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}
