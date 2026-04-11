import { useMemo, useState } from 'react';

import type { StrategyBuilderGenerateResponse } from '../../types/api';

type RuleNode = Record<string, unknown>;

function prettifyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return '{}';
  }
}

function formatPercent(value: unknown, digits = 1): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

function formatCurrency(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0
  }).format(value);
}

function formatBps(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return `${value} bps`;
}

function titleCase(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function compactRuleLabel(type: unknown): string {
  if (typeof type !== 'string' || !type.trim()) return 'Unknown rule';
  return titleCase(type);
}

function explainAtomicRule(rule: RuleNode): string {
  const type = typeof rule.type === 'string' ? rule.type : 'unknown_rule';
  const symbol = typeof rule.symbol === 'string' ? rule.symbol : null;
  const lookback = typeof rule.lookback === 'number' ? rule.lookback : null;
  const threshold = typeof rule.threshold === 'number' ? rule.threshold : null;
  const fastWindow = typeof rule.fast_window === 'number' ? rule.fast_window : null;
  const slowWindow = typeof rule.slow_window === 'number' ? rule.slow_window : null;
  const monthValues = Array.isArray(rule.month_values)
    ? rule.month_values.filter((value): value is number => typeof value === 'number')
    : [];

  switch (type) {
    case 'rsi_below':
      return `${symbol ?? 'Asset'} RSI${lookback ? `(${lookback})` : ''} falls below ${
        threshold ?? '—'
      }`;
    case 'rsi_above':
      return `${symbol ?? 'Asset'} RSI${lookback ? `(${lookback})` : ''} rises above ${
        threshold ?? '—'
      }`;
    case 'sma_cross_above':
      return `${symbol ?? 'Asset'} ${fastWindow ?? 'fast'}-day SMA crosses above ${
        slowWindow ?? 'slow'
      }-day SMA`;
    case 'sma_cross_below':
      return `${symbol ?? 'Asset'} ${fastWindow ?? 'fast'}-day SMA crosses below ${
        slowWindow ?? 'slow'
      }-day SMA`;
    case 'macd_bullish_cross':
      return `${symbol ?? 'Asset'} MACD turns bullish`;
    case 'macd_bearish_cross':
      return `${symbol ?? 'Asset'} MACD turns bearish`;
    case 'month_in':
      return monthValues.length > 0
        ? `Only trade during months ${monthValues.join(', ')}`
        : 'Month filter is applied';
    default:
      return `${compactRuleLabel(type)}${symbol ? ` on ${symbol}` : ''}`;
  }
}

function explainRule(rule: unknown): string {
  if (!rule || typeof rule !== 'object') return 'No rule defined';

  const node = rule as RuleNode;
  const kind = typeof node.kind === 'string' ? node.kind : 'atomic';

  if (kind === 'atomic') {
    return explainAtomicRule(node);
  }

  if (kind === 'sequence') {
    const steps = Array.isArray(node.steps) ? node.steps : [];
    const windowBars = typeof node.window_bars === 'number' ? node.window_bars : null;
    const explainedSteps = steps.map((step) => explainRule(step));
    return explainedSteps.length > 0
      ? `Sequence${windowBars ? ` within ${windowBars} bars` : ''}: ${explainedSteps.join(
          ' → '
        )}`
      : 'Sequence rule';
  }

  if (kind === 'group') {
    const operator = typeof node.operator === 'string' ? node.operator.toUpperCase() : 'AND';
    const rules = Array.isArray(node.rules) ? node.rules : [];
    const explainedRules = rules.map((child) => explainRule(child));
    return explainedRules.length > 0
      ? `${operator} group: ${explainedRules.join(` ${operator} `)}`
      : `${operator} group`;
  }

  return compactRuleLabel(typeof node.type === 'string' ? node.type : 'Unknown');
}

function InfoPill({
  label,
  value
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-sm text-slate-100">{value ?? '—'}</div>
    </div>
  );
}

function Section({
  eyebrow,
  title,
  children
}: {
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-950/60 p-5">
      {eyebrow ? (
        <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-cyan-300">
          {eyebrow}
        </div>
      ) : null}
      <h3 className="mt-1 text-sm font-semibold text-white">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function BulletList({
  items,
  emptyText,
  tone = 'default'
}: {
  items: string[];
  emptyText: string;
  tone?: 'default' | 'warning' | 'success';
}) {
  const bulletClass =
    tone === 'warning'
      ? 'text-amber-300'
      : tone === 'success'
      ? 'text-emerald-300'
      : 'text-cyan-300';

  if (items.length === 0) {
    return <p className="text-sm text-slate-400">{emptyText}</p>;
  }

  return (
    <ul className="space-y-2 text-sm text-slate-100">
      {items.map((item, index) => (
        <li key={`${item}-${index}`} className="flex gap-2">
          <span className={bulletClass}>•</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
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

  const viewModel = useMemo(() => {
    const config = draft.config ?? {};
    const allocation =
      (config.allocation as Record<string, unknown> | undefined) ?? {};
    const risk = (config.risk as Record<string, unknown> | undefined) ?? {};
    const coreOverlay =
      (config.core_overlay as Record<string, unknown> | undefined) ?? {};

    const entryRule = config.entry_rule;
    const exitRule = config.exit_rule;

    const entryValue =
      typeof allocation.entry_value === 'number'
        ? `${(allocation.entry_value * 100).toFixed(1)}% of equity`
        : '—';

    const maxPosition =
      typeof allocation.max_position_pct === 'number'
        ? `${(allocation.max_position_pct * 100).toFixed(1)}%`
        : '—';

    const stopLoss = formatPercent(risk.stop_loss_pct);
    const takeProfit = formatPercent(risk.take_profit_pct);
    const cooldown =
      typeof risk.cooldown_bars === 'number'
        ? risk.cooldown_bars === 0
          ? 'None'
          : `${risk.cooldown_bars} bars`
        : '—';

    const coreOverlayEnabled = coreOverlay.enabled === true;
    const coreAllocation =
      typeof coreOverlay.core_allocation_pct === 'number'
        ? `${(coreOverlay.core_allocation_pct * 100).toFixed(1)}% core`
        : '—';

    const strategyHeadline =
      typeof config.name === 'string' && config.name.trim()
        ? config.name
        : 'Generated strategy';

    const readableExplanation = [
      `Trade ${typeof config.tradable_symbol === 'string' ? config.tradable_symbol : 'the selected asset'} from ${
        typeof config.start_date === 'string' ? config.start_date : 'the chosen start date'
      } to ${typeof config.end_date === 'string' ? config.end_date : 'the chosen end date'}.`,
      `Enter when ${explainRule(entryRule)}.`,
      `Exit when ${explainRule(exitRule)}.`,
      typeof allocation.entry_value === 'number'
        ? `Use ${(allocation.entry_value * 100).toFixed(1)}% of equity per entry.`
        : null,
      typeof risk.stop_loss_pct === 'number'
        ? `Protect downside with a ${formatPercent(risk.stop_loss_pct)} stop loss.`
        : null,
      typeof risk.take_profit_pct === 'number'
        ? `Take profit at ${formatPercent(risk.take_profit_pct)}.`
        : null,
      typeof risk.cooldown_bars === 'number' && risk.cooldown_bars > 0
        ? `Wait ${risk.cooldown_bars} bars before re-entering after an exit.`
        : null
    ].filter((item): item is string => Boolean(item));

    return {
      strategyHeadline,
      tradableSymbol:
        typeof config.tradable_symbol === 'string' ? config.tradable_symbol : '—',
      benchmarkSymbol:
        typeof config.benchmark_symbol === 'string' ? config.benchmark_symbol : '—',
      startDate: typeof config.start_date === 'string' ? config.start_date : '—',
      endDate: typeof config.end_date === 'string' ? config.end_date : '—',
      initialCapital: formatCurrency(config.initial_capital),
      transactionCost: formatBps(config.transaction_cost_bps),
      allocationMode:
        typeof allocation.entry_mode === 'string' ? titleCase(allocation.entry_mode) : '—',
      entryValue,
      maxPosition,
      entryRuleLabel: explainRule(entryRule),
      exitRuleLabel: explainRule(exitRule),
      stopLoss,
      takeProfit,
      cooldown,
      coreOverlayLabel: coreOverlayEnabled ? `Enabled · ${coreAllocation}` : 'Disabled',
      readableExplanation
    };
  }, [draft]);

  const hasChanges = draft.changes.length > 0;
  const hasWarnings = draft.warnings.length > 0;

  return (
    <div className="space-y-4">
      <div className="rounded-[32px] border border-slate-800 bg-slate-900/80 p-5 shadow-2xl shadow-black/20">
        <div className="flex flex-col gap-4 border-b border-slate-800 pb-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-cyan-900/70 bg-cyan-950/40 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-300">
                {hasChanges ? 'Updated Draft' : 'Strategy Draft'}
              </span>
              {hasWarnings ? (
                <span className="rounded-full border border-amber-900/70 bg-amber-950/40 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-amber-300">
                  Review warnings
                </span>
              ) : (
                <span className="rounded-full border border-emerald-900/70 bg-emerald-950/30 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">
                  Ready to simulate
                </span>
              )}
            </div>

            <div>
              <h2 className="text-lg font-semibold tracking-tight text-white">
                {viewModel.strategyHeadline}
              </h2>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-200">
                {draft.summary}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setShowConfig((value) => !value)}
              className="rounded-2xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-900"
            >
              {showConfig ? 'Hide JSON' : 'Show JSON'}
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

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <InfoPill label="Tradable Symbol" value={viewModel.tradableSymbol} />
          <InfoPill label="Benchmark" value={viewModel.benchmarkSymbol} />
          <InfoPill label="Start Date" value={viewModel.startDate} />
          <InfoPill label="End Date" value={viewModel.endDate} />
          <InfoPill label="Initial Capital" value={viewModel.initialCapital} />
          <InfoPill label="Transaction Cost" value={viewModel.transactionCost} />
          <InfoPill label="Allocation" value={viewModel.entryValue} />
          <InfoPill label="Max Position" value={viewModel.maxPosition} />
        </div>

        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          <Section eyebrow="Readable explanation" title="How this strategy trades">
            <BulletList
              items={viewModel.readableExplanation}
              emptyText="No explanation available."
              tone="success"
            />
          </Section>

          <Section eyebrow="Signal logic" title="Entry and exit rules">
            <div className="space-y-3 text-sm text-slate-100">
              <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                  Entry
                </div>
                <div className="mt-2 leading-6">{viewModel.entryRuleLabel}</div>
              </div>
              <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                  Exit
                </div>
                <div className="mt-2 leading-6">{viewModel.exitRuleLabel}</div>
              </div>
            </div>
          </Section>

          <Section eyebrow="Risk controls" title="Protection and portfolio behavior">
            <div className="grid gap-3 sm:grid-cols-2">
              <InfoPill label="Stop Loss" value={viewModel.stopLoss} />
              <InfoPill label="Take Profit" value={viewModel.takeProfit} />
              <InfoPill label="Cooldown" value={viewModel.cooldown} />
              <InfoPill label="Core / Overlay" value={viewModel.coreOverlayLabel} />
            </div>
          </Section>

          <Section eyebrow="Revision history" title="What changed in this draft">
            <BulletList
              items={draft.changes}
              emptyText="No explicit config changes were detected."
            />
          </Section>
        </div>

        {hasWarnings ? (
          <div className="mt-4 rounded-3xl border border-amber-900/60 bg-amber-950/20 p-5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-amber-300">
              Warnings
            </div>
            <div className="mt-3">
              <BulletList
                items={draft.warnings}
                emptyText="No warnings."
                tone="warning"
              />
            </div>
          </div>
        ) : null}

        {runError ? (
          <div className="mt-4 rounded-2xl border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
            {runError}
          </div>
        ) : null}

        {showConfig ? (
          <div className="mt-4 rounded-3xl border border-slate-800 bg-slate-950 p-5">
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
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