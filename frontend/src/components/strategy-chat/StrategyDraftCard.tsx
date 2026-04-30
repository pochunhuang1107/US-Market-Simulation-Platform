import { useMemo, useState } from 'react';

import { explainRule } from '../../lib/ruleSummaries';
import type { StrategyBuilderGenerateResponse } from '../../types/api';

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

function InfoPill({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="app-home-draft-panel rounded-2xl px-4 py-3">
      <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">{label}</div>
      <div className="app-title mt-1 text-sm">{value ?? '—'}</div>
    </div>
  );
}

function Section({ eyebrow, title, children }: { eyebrow?: string; title: string; children: React.ReactNode }) {
  return (
    <section className="app-home-draft-section rounded-3xl p-5">
      {eyebrow ? <div className="app-accent text-[11px] font-semibold uppercase tracking-[0.24em]">{eyebrow}</div> : null}
      <h3 className="app-title mt-1 text-sm font-semibold">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function BulletList({ items, emptyText, tone = 'default' }: { items: string[]; emptyText: string; tone?: 'default' | 'warning' | 'success' }) {
  const markerClass =
    tone === 'warning'
      ? 'border-amber-400/40 bg-amber-500/10'
      : tone === 'success'
        ? 'border-emerald-400/40 bg-emerald-500/10'
        : 'border-cyan-400/40 bg-cyan-500/10';

  const dotClass =
    tone === 'warning'
      ? 'bg-amber-300'
      : tone === 'success'
        ? 'bg-emerald-300'
        : 'bg-cyan-300';

  if (items.length === 0) return <p className="app-text-muted text-sm">{emptyText}</p>;

  return (
    <ul className="space-y-2 text-sm">
      {items.map((item, index) => (
        <li key={`${item}-${index}`} className="app-title flex items-start gap-2">
          <span
            aria-hidden="true"
            className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${markerClass}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} />
          </span>
          <span className="min-w-0 leading-6">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function QuickEditChip({
  text,
  onClick
}: {
  text: string;
  onClick: (prompt: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick(text)}
      className="app-note inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-left text-sm font-semibold transition hover:opacity-90 cursor-pointer shadow-sm"
    >
      <span>{text}</span>
      <span aria-hidden="true">↗</span>
    </button>
  );
}

export function StrategyDraftCard({
  draft,
  onRun,
  onUsePrompt,
  isLatestDraft = true,
  isRunning = false,
  runError = null
}: {
  draft: StrategyBuilderGenerateResponse;
  onRun: () => void;
  onUsePrompt?: (prompt: string) => void;
  isLatestDraft?: boolean;
  isRunning?: boolean;
  runError?: string | null;
}) {
  const [showConfig, setShowConfig] = useState(false);

  const viewModel = useMemo(() => {
    const config = draft.config ?? {};
    const allocation = (config.allocation as Record<string, unknown> | undefined) ?? {};
    const risk = (config.risk as Record<string, unknown> | undefined) ?? {};
    const coreOverlay = (config.core_overlay as Record<string, unknown> | undefined) ?? {};

    const entryValue = typeof allocation.entry_value === 'number' ? `${(allocation.entry_value * 100).toFixed(1)}% of equity` : '—';
    const maxPosition = typeof allocation.max_position_pct === 'number' ? `${(allocation.max_position_pct * 100).toFixed(1)}%` : '—';
    const stopLoss = formatPercent(risk.stop_loss_pct);
    const takeProfit = formatPercent(risk.take_profit_pct);
    const cooldown = typeof risk.cooldown_bars === 'number' ? (risk.cooldown_bars === 0 ? 'None' : `${risk.cooldown_bars} bars`) : '—';
    const coreOverlayEnabled = coreOverlay.enabled === true;
    const coreAllocationValue = typeof coreOverlay.core_allocation_pct === 'number' ? `${(coreOverlay.core_allocation_pct * 100).toFixed(1)}%` : '—';
    const overlayAllocationValue =
      typeof coreOverlay.core_allocation_pct === 'number'
        ? `${((1 - coreOverlay.core_allocation_pct) * 100).toFixed(1)}%`
        : '—';
    const coreAllocation = coreAllocationValue === '—' ? '—' : `${coreAllocationValue} core`;
    const overlaySleeveAllocation =
      overlayAllocationValue === '—' ? '—' : `${overlayAllocationValue} overlay`;
    const strategyHeadline = typeof config.name === 'string' && config.name.trim() ? config.name : 'Generated strategy';

    return {
      strategyHeadline,
      tradableSymbol: typeof config.tradable_symbol === 'string' ? config.tradable_symbol : '—',
      benchmarkSymbol: typeof config.benchmark_symbol === 'string' ? config.benchmark_symbol : '—',
      startDate: typeof config.start_date === 'string' ? config.start_date : '—',
      endDate: typeof config.end_date === 'string' ? config.end_date : '—',
      initialCapital: formatCurrency(config.initial_capital),
      transactionCost: formatBps(config.transaction_cost_bps),
      entryValue,
      maxPosition,
      coreOverlayEnabled,
      coreAllocationValue,
      overlayAllocationValue,
      entryRuleLabel: explainRule(config.entry_rule, { tradableSymbol: config.tradable_symbol }),
      exitRuleLabel: explainRule(config.exit_rule, { tradableSymbol: config.tradable_symbol }),
      stopLoss,
      takeProfit,
      cooldown,
      coreOverlayLabel: coreOverlayEnabled ? `Enabled · ${coreAllocation} · ${overlaySleeveAllocation}` : 'Disabled',
      readableExplanation: [
        `Trade ${typeof config.tradable_symbol === 'string' ? config.tradable_symbol : 'the selected asset'} from ${typeof config.start_date === 'string' ? config.start_date : 'the chosen start date'} to ${typeof config.end_date === 'string' ? config.end_date : 'the chosen end date'}.`,
        typeof config.benchmark_symbol === 'string'
          ? `Compare performance against ${config.benchmark_symbol}.`
          : null,
        `Enter when ${explainRule(config.entry_rule, { tradableSymbol: config.tradable_symbol })}.`,
        `Exit when ${explainRule(config.exit_rule, { tradableSymbol: config.tradable_symbol })}.`,
        !coreOverlayEnabled && typeof allocation.entry_value === 'number'
          ? `Use ${(allocation.entry_value * 100).toFixed(1)}% of equity per entry.`
          : null,
        !coreOverlayEnabled && typeof allocation.max_position_pct === 'number'
          ? `Cap any single position at ${(allocation.max_position_pct * 100).toFixed(1)}% of equity.`
          : null,
        coreOverlayEnabled && typeof coreOverlay.core_allocation_pct === 'number'
          ? `Keep ${coreAllocationValue} in the core sleeve.`
          : null,
        coreOverlayEnabled && typeof coreOverlay.core_allocation_pct === 'number'
          ? `Use ${overlayAllocationValue} for the tactical overlay sleeve.`
          : null,
        coreOverlayEnabled && typeof allocation.max_position_pct === 'number'
          ? `Cap overlay positions at ${(allocation.max_position_pct * 100).toFixed(1)}% of equity.`
          : null,
        typeof risk.stop_loss_pct === 'number'
          ? `Protect downside with a ${formatPercent(risk.stop_loss_pct)} stop loss.`
          : null,
        typeof risk.take_profit_pct === 'number'
          ? `Take profit at ${formatPercent(risk.take_profit_pct)}.`
          : null,
        typeof risk.cooldown_bars === 'number' && risk.cooldown_bars > 0
          ? `Wait ${risk.cooldown_bars} bars before re-entering after an exit.`
          : null,
      ].filter((item): item is string => Boolean(item))
    };
  }, [draft]);

  const quickEditPrompts = useMemo(() => {
    const config = draft.config ?? {};
    const risk = (config.risk as Record<string, unknown> | undefined) ?? {};
    const allocation = (config.allocation as Record<string, unknown> | undefined) ?? {};
    const coreOverlay = (config.core_overlay as Record<string, unknown> | undefined) ?? {};
    const entryRule = (config.entry_rule as Record<string, unknown> | undefined) ?? {};
    const exitRule = (config.exit_rule as Record<string, unknown> | undefined) ?? {};
    const coreOverlayEnabled = coreOverlay.enabled === true;

    const prompts: string[] = [];

    if (typeof config.benchmark_symbol === 'string') {
      prompts.push(
        config.benchmark_symbol === 'SPY'
          ? 'Change benchmark to QQQ'
          : 'Change benchmark to SPY'
      );
    }

    if (typeof risk.stop_loss_pct === 'number') {
      prompts.push('Remove stop loss');
    } else {
      prompts.push('Add 10% stop loss');
    }

    if (typeof risk.take_profit_pct === 'number') {
      prompts.push('Remove take profit');
    } else {
      prompts.push('Add 15% take profit');
    }

    if (coreOverlayEnabled) {
      prompts.push('Change overlay allocation to 30%');
    } else {
      if (typeof allocation.max_position_pct === 'number' && allocation.max_position_pct >= 1) {
        prompts.push('Change max position to 50%');
      } else {
        prompts.push('Change max position to 100%');
      }
    }

    if (typeof exitRule.slow_window === 'number') {
      prompts.push(`Change exit slow window to ${exitRule.slow_window + 5}`);
    }

    if (typeof entryRule.type === 'string' && entryRule.type !== 'macd_bullish_cross') {
      prompts.push('Change this strategy to MACD');
    }

    prompts.push('Explain this draft in simple terms');

    return Array.from(new Set(prompts)).slice(0, 6);
  }, [draft]);

  const hasChanges = draft.changes.length > 0;
  const hasWarnings = draft.warnings.length > 0;

  return (
    <div className="space-y-4">
      <div className="app-card app-home-draft-card app-shadow rounded-[32px] border p-5">
        <div className="app-divider flex flex-col gap-4 border-b pb-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="app-chip-info rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]">
                {hasChanges ? 'Updated Draft' : 'Strategy Draft'}
              </span>
              {hasWarnings ? (
                <span className="app-chip-warning rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]">Review warnings</span>
              ) : (
                <span className="app-chip-success rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]">Ready to simulate</span>
              )}
            </div>
            <div>
              <h2 className="app-title text-lg font-semibold tracking-tight">{viewModel.strategyHeadline}</h2>
              <p className="app-text-muted mt-2 whitespace-pre-wrap text-sm leading-6">{draft.summary}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => setShowConfig((value) => !value)} className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition">
              {showConfig ? 'Hide JSON' : 'Show JSON'}
            </button>
            {isLatestDraft ? (
              <button type="button" onClick={onRun} disabled={isRunning} className="app-button-primary rounded-2xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60">
                {isRunning ? 'Running...' : 'Run Simulation'}
              </button>
            ) : (
              <div className="app-surface-soft rounded-2xl border px-4 py-2 text-sm font-medium app-text-muted">
                Superseded by a newer draft
              </div>
            )}
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <InfoPill label="Tradable Symbol" value={viewModel.tradableSymbol} />
          <InfoPill label="Benchmark" value={viewModel.benchmarkSymbol} />
          <InfoPill label="Start Date" value={viewModel.startDate} />
          <InfoPill label="End Date" value={viewModel.endDate} />
          <InfoPill label="Initial Capital" value={viewModel.initialCapital} />
          <InfoPill label="Transaction Cost" value={viewModel.transactionCost} />
          {viewModel.coreOverlayEnabled ? (
            <>
              <InfoPill label="Core Allocation" value={viewModel.coreAllocationValue} />
              <InfoPill label="Overlay Allocation" value={viewModel.overlayAllocationValue} />
              <InfoPill label="Overlay Max Position" value={viewModel.maxPosition} />
            </>
          ) : (
            <>
              <InfoPill label="Allocation" value={viewModel.entryValue} />
              <InfoPill label="Max Position" value={viewModel.maxPosition} />
            </>
          )}
        </div>

        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          <Section eyebrow="Readable explanation" title="How this strategy trades">
            <BulletList items={viewModel.readableExplanation} emptyText="No explanation available." tone="success" />
          </Section>

          <Section eyebrow="Default choices" title="Why these defaults were chosen">
            <BulletList
              items={draft.assumptions}
              emptyText="No default assumptions were needed."
              tone="success"
            />
          </Section>

          <Section eyebrow="Signal logic" title="Entry and exit rules">
            <div className="space-y-3 text-sm">
              <div className="app-home-draft-panel rounded-2xl p-4">
                <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">Entry</div>
                <div className="app-title mt-2 leading-6">{viewModel.entryRuleLabel}</div>
              </div>
              <div className="app-home-draft-panel rounded-2xl p-4">
                <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">Exit</div>
                <div className="app-title mt-2 leading-6">{viewModel.exitRuleLabel}</div>
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

          <Section eyebrow="Quick edits" title="Common next adjustments">
            <div className="flex flex-wrap gap-2">
              {quickEditPrompts.map((prompt) => (
                <QuickEditChip
                  key={prompt}
                  text={prompt}
                  onClick={(nextPrompt) => onUsePrompt?.(nextPrompt)}
                />
              ))}
            </div>
          </Section>

          <Section eyebrow="Revision history" title="What changed in this draft">
            <BulletList items={draft.changes} emptyText="No explicit config changes were detected." />
          </Section>
        </div>

        {hasWarnings ? (
          <div className="app-alert-warning mt-4 rounded-3xl p-5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.22em]">Warnings</div>
            <div className="mt-3">
              <BulletList items={draft.warnings} emptyText="No warnings." tone="warning" />
            </div>
          </div>
        ) : null}

        {runError ? <div className="app-alert-error mt-4 rounded-2xl px-4 py-3 text-sm">{runError}</div> : null}

        {showConfig ? (
          <div className="app-home-json-panel mt-4 rounded-3xl p-5">
            <div className="app-label mb-3 text-[11px] font-semibold uppercase tracking-[0.22em]">Canonical Strategy V2 JSON</div>
            <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6">{prettifyJson(draft.config)}</pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}
