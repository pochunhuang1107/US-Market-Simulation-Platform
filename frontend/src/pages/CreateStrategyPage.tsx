import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { createStrategy } from '../lib/api';
import type { CreateStrategyRequest } from '../types/api';

const DEFAULT_CONFIG = `{
  "schema_version": "2.0",
  "name": "qqq-rsi-test",
  "tradable_symbol": "QQQ",
  "benchmark_symbol": "QQQ",
  "start_date": "2018-01-02",
  "end_date": "2024-12-31",
  "initial_capital": 100000,
  "transaction_cost_bps": 5,
  "allocation": {
    "entry_mode": "percent_of_equity",
    "entry_value": 1.0,
    "max_position_pct": 1.0
  },
  "entry_rule": {
    "kind": "atomic",
    "type": "rsi_below",
    "symbol": "QQQ",
    "lookback": 14,
    "threshold": 30
  },
  "exit_rule": {
    "kind": "atomic",
    "type": "rsi_above",
    "symbol": "QQQ",
    "lookback": 14,
    "threshold": 70
  },
  "risk": {
    "stop_loss_pct": 0.1,
    "cooldown_bars": 0
  },
  "core_overlay": {
    "enabled": false,
    "core_allocation_pct": 0.0
  }
}`;

const STRATEGY_TYPE_OPTIONS = [
  { value: 'SIMULATION', label: 'Single ETF' },
  { value: 'PORTFOLIO', label: 'Portfolio' },
  { value: 'COMPARISON', label: 'Comparison' },
  { value: 'PARAMETER_SWEEP', label: 'Parameter Sweep' }
] as const;

type CreateStrategyLocationState = {
  builderDraft?: {
    name?: string;
    description?: string;
    strategyType?: string;
    configText?: string;
  };
};

type JsonRecord = Record<string, unknown>;

function normalizeError(error: unknown): string {
  const message = error instanceof Error ? error.message : 'Something went wrong.';

  if (message.includes('Saved strategy limit reached')) {
    return 'Saved strategy limit reached. Go to Strategy Library and archive an older strategy, then try saving again.';
  }

  return message;
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function safeParseConfig(value: string): JsonRecord | null {
  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function prettifyJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function formatStrategyType(value: string): string {
  return (
    STRATEGY_TYPE_OPTIONS.find((option) => option.value === value)?.label ??
    value
      .toLowerCase()
      .split('_')
      .filter(Boolean)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  );
}

function formatCurrency(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0
  }).format(value);
}

function formatPercent(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';

  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return `${pct.toFixed(Number.isInteger(pct) ? 0 : 1)}%`;
}

function formatBps(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return `${value.toLocaleString()} bps`;
}

function formatSymbol(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim().toUpperCase() : '—';
}

function formatDateRange(config: JsonRecord): string {
  const startDate = typeof config.start_date === 'string' ? config.start_date : '';
  const endDate = typeof config.end_date === 'string' ? config.end_date : '';

  if (startDate && endDate) return `${startDate} → ${endDate}`;
  if (startDate) return `From ${startDate}`;
  if (endDate) return `Through ${endDate}`;
  return '—';
}

function formatRule(rule: unknown): string {
  return summarizeRule(rule).text;
}

function summarizeRule(
  rule: unknown,
  depth = 0
): { text: string; kind: 'empty' | 'simple' | 'complex' | 'custom' } {
  if (!isRecord(rule)) return { text: '—', kind: 'empty' };

  if ((rule.kind === 'group' || rule.type === 'group') && Array.isArray(rule.rules)) {
    if (depth > 0 || rule.rules.length > 3) {
      return { text: 'Complex rule group · review JSON', kind: 'complex' };
    }

    const operator =
      typeof rule.operator === 'string' && ['AND', 'OR'].includes(rule.operator.toUpperCase())
        ? rule.operator.toUpperCase()
        : 'AND';
    const summaries = rule.rules.map((childRule) => summarizeRule(childRule, depth + 1));
    const usableSummaries = summaries.filter((summary) => summary.kind === 'simple');

    if (usableSummaries.length !== rule.rules.length || usableSummaries.length === 0) {
      return { text: 'Complex rule group · review JSON', kind: 'complex' };
    }

    return {
      text: usableSummaries.map((summary) => summary.text).join(` ${operator} `),
      kind: 'simple'
    };
  }

  if (
    rule.kind === 'window' ||
    rule.kind === 'sequence' ||
    rule.type === 'window' ||
    rule.type === 'sequence'
  ) {
    return { text: 'Complex rule group · review JSON', kind: 'complex' };
  }

  const atomicSummary = summarizeAtomicRule(rule);
  if (atomicSummary) {
    return { text: atomicSummary, kind: 'simple' };
  }

  return { text: 'Custom rule · review JSON', kind: 'custom' };
}

function summarizeAtomicRule(rule: JsonRecord): string | null {
  const type = typeof rule.type === 'string' ? rule.type : '';
  const symbol = formatSymbol(rule.symbol);
  const lookback = typeof rule.lookback === 'number' ? rule.lookback : null;
  const threshold = typeof rule.threshold === 'number' ? rule.threshold : null;
  const fastWindow = typeof rule.fast_window === 'number' ? rule.fast_window : 'fast';
  const slowWindow = typeof rule.slow_window === 'number' ? rule.slow_window : 'slow';

  switch (type) {
    case 'rsi_below':
      return `${symbol} RSI${lookback ? ` ${lookback}` : ''} below ${threshold ?? 'threshold'}`;
    case 'rsi_above':
      return `${symbol} RSI${lookback ? ` ${lookback}` : ''} above ${threshold ?? 'threshold'}`;
    case 'sma_cross_above':
      return `${symbol} SMA ${fastWindow} crosses above SMA ${slowWindow}`;
    case 'sma_cross_below':
      return `${symbol} SMA ${fastWindow} crosses below SMA ${slowWindow}`;
    case 'sma_above':
      return `${symbol} SMA ${fastWindow} above SMA ${slowWindow}`;
    case 'macd_bullish_cross':
      return `${symbol} MACD bullish cross`;
    case 'kd_golden_cross':
      return `${symbol} stochastic KD golden cross`;
    case 'relative_return_above':
      return `${symbol} beats ${formatSymbol(rule.reference_symbol)} by ${formatPercent(rule.threshold)} over ${lookback ?? 'lookback'} bars`;
    case 'month_in':
      return Array.isArray(rule.month_values)
        ? `Month is ${rule.month_values.join(', ')}`
        : 'Month filter';
    default:
      return summarizeThresholdRule(rule, type);
  }
}

function summarizeThresholdRule(rule: JsonRecord, type: string): string | null {
  const value =
    typeof rule.threshold === 'number'
      ? rule.threshold
      : typeof rule.value === 'number'
        ? rule.value
        : null;

  if (value === null) return null;

  const operatorFromType = type.endsWith('_above')
    ? 'above'
    : type.endsWith('_below')
      ? 'below'
      : null;
  const operator =
    operatorFromType ??
    (typeof rule.operator === 'string' &&
    ['above', 'below'].includes(rule.operator.toLowerCase())
      ? rule.operator.toLowerCase()
      : null);

  if (!operator) return null;

  const rawSubject =
    typeof rule.symbol === 'string'
      ? rule.symbol
      : typeof rule.indicator === 'string'
        ? rule.indicator
        : type.startsWith('vix_')
          ? 'VIX'
          : '';
  const subject = formatSymbol(rawSubject);

  if (subject === '—') return null;

  return `${subject} ${operator} ${value}`;
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
        {label}
      </span>
      {children}
    </label>
  );
}

export function CreateStrategyPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const builderDraft = useMemo(() => {
    return (location.state as CreateStrategyLocationState | null)?.builderDraft ?? null;
  }, [location.state]);

  const [name, setName] = useState(builderDraft?.name ?? '');
  const [description, setDescription] = useState(builderDraft?.description ?? '');
  const [strategyType, setStrategyType] = useState(builderDraft?.strategyType ?? 'SIMULATION');
  const [configText, setConfigText] = useState(builderDraft?.configText ?? DEFAULT_CONFIG);

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const parsedConfig = useMemo(() => safeParseConfig(configText), [configText]);

  const inputClassName =
    'app-version-input w-full rounded-2xl px-4 py-3 text-sm outline-none transition';
  const textareaClassName =
    'app-json-editor min-h-[460px] w-full rounded-2xl px-4 py-3 font-mono text-sm leading-6 outline-none transition';

  async function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);

    if (!name.trim()) {
      setSubmitError('Strategy name is required.');
      return;
    }

    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = JSON.parse(configText) as Record<string, unknown>;
    } catch {
      setSubmitError('Config must be valid JSON.');
      return;
    }

    const payload: CreateStrategyRequest = {
      name: name.trim(),
      description: description.trim() || null,
      strategy_type: strategyType,
      config: parsedConfig
    };

    setSubmitting(true);

    try {
      const response = await createStrategy(payload);
      navigate(`/strategies/${response.strategy_id}`);
    } catch (error) {
      setSubmitError(normalizeError(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="app-eyebrow text-xs font-semibold uppercase tracking-[0.28em]">
            Advanced Strategy Create
          </div>
          <h1 className="app-title mt-2 text-3xl font-semibold tracking-tight">
            Manual Strategy Create
          </h1>
          <p className="app-text-muted mt-3 max-w-3xl text-sm">
            Create a saved strategy manually when you already have a structured config.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to="/strategies"
            className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition"
          >
            Back to Strategy Library
          </Link>
        </div>
      </div>

      {builderDraft && (
        <div className="app-note mb-6 rounded-2xl border px-4 py-3 text-sm">
          Prefilled from Strategy Builder. Review the draft and save when ready.
        </div>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.85fr)]">
        <form
          onSubmit={handleSubmit}
          className="app-card app-shadow rounded-3xl border p-6"
        >
          <div className="mb-6">
            <h2 className="app-title text-xl font-semibold">Strategy Details</h2>
            <p className="app-text-muted mt-2 text-sm">
              Name the strategy, choose its type, and review the config that will become version 1.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <Field label="Strategy Name">
              <input
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="qqq-rsi-test"
                className={inputClassName}
              />
            </Field>

            <Field label="Strategy Type">
              <select
                value={strategyType}
                onChange={(event) => setStrategyType(event.target.value)}
                className={inputClassName}
              >
                {STRATEGY_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>

            <div className="md:col-span-2">
              <Field label="Description">
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Optional description"
                  className="app-version-input min-h-[110px] w-full rounded-2xl px-4 py-3 text-sm outline-none transition"
                />
              </Field>
            </div>

            <div className="md:col-span-2">
              <Field label="Config JSON">
                <textarea
                  value={configText}
                  onChange={(event) => setConfigText(event.target.value)}
                  className={textareaClassName}
                  spellCheck={false}
                />
              </Field>
            </div>
          </div>

          {submitError && (
            <div className="app-validation-error mt-6 rounded-2xl px-4 py-3 text-sm">
              <p>{submitError}</p>
              {submitError.includes('Saved strategy limit reached') ? (
                <Link
                  to="/strategies"
                  className="mt-3 inline-flex rounded-xl border px-3 py-2 text-xs font-semibold transition hover:opacity-80"
                >
                  Open Strategy Library
                </Link>
              ) : null}
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="app-button-primary rounded-2xl px-5 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Creating Strategy...' : 'Create Strategy'}
            </button>

            <button
              type="button"
              onClick={() => setConfigText(prettifyJson(builderDraft?.configText ?? DEFAULT_CONFIG))}
              className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-medium transition"
            >
              {builderDraft ? 'Reset to Builder Draft' : 'Reset Config'}
            </button>
          </div>
        </form>

        <div className="space-y-6">
          <section className="app-card app-shadow rounded-3xl border p-6">
            <h2 className="app-title text-xl font-semibold">Strategy Preview</h2>
            <p className="app-text-muted mt-2 text-sm">
              Review the saved strategy details before creating version 1.
            </p>

            <div className="mt-5 space-y-3">
              <div className="app-surface-soft rounded-2xl border px-4 py-4">
                <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
                  Name
                </div>
                <div className="app-title mt-2 break-words text-sm">{name || '—'}</div>
              </div>

              <div className="app-surface-soft rounded-2xl border px-4 py-4">
                <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
                  Strategy Type
                </div>
                <div className="app-title mt-2 break-words text-sm">
                  {formatStrategyType(strategyType)}
                </div>
              </div>

              <div className="app-surface-soft rounded-2xl border px-4 py-4">
                <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
                  Description
                </div>
                <div className="app-title mt-2 whitespace-pre-wrap break-words text-sm">
                  {description || '—'}
                </div>
              </div>
            </div>
          </section>

          <section className="app-card app-shadow rounded-3xl border p-6">
            <h2 className="app-title text-xl font-semibold">Config Summary</h2>
            <p className="app-text-muted mt-2 text-sm">
              Human-readable highlights from the config that will become version 1.
            </p>

            <ConfigSummary config={parsedConfig} />
          </section>
        </div>
      </div>
    </div>
  );
}

function ConfigSummary({ config }: { config: JsonRecord | null }) {
  if (!config) {
    return (
      <div className="app-surface-soft app-text-muted mt-5 rounded-2xl border px-4 py-3 text-sm">
        Fix the JSON to preview the strategy summary.
      </div>
    );
  }

  const risk = isRecord(config.risk) ? config.risk : null;
  const coreOverlay = isRecord(config.core_overlay) ? config.core_overlay : null;

  return (
    <div className="app-surface-soft mt-5 overflow-hidden rounded-2xl border">
      <SummaryRow label="Tradable" value={formatSymbol(config.tradable_symbol)} />
      <SummaryRow label="Benchmark" value={formatSymbol(config.benchmark_symbol)} />
      <SummaryRow label="Window" value={formatDateRange(config)} />
      <SummaryRow
        label="Capital"
        value={`${formatCurrency(config.initial_capital)} · ${formatBps(config.transaction_cost_bps)}`}
      />
      <SummaryRow label="Entry" value={formatRule(config.entry_rule)} />
      <SummaryRow label="Exit" value={formatRule(config.exit_rule)} />
      <SummaryRow label="Risk" value={formatRiskSummary(risk)} />
      <SummaryRow label="Core / Overlay" value={formatCoreOverlaySummary(coreOverlay)} />
    </div>
  );
}

function formatRiskSummary(risk: JsonRecord | null): string {
  if (!risk) return '—';

  const parts = [
    risk.stop_loss_pct !== undefined ? `Stop loss ${formatPercent(risk.stop_loss_pct)}` : null,
    risk.take_profit_pct !== undefined ? `Take profit ${formatPercent(risk.take_profit_pct)}` : null,
    risk.cooldown_bars !== undefined ? `Cooldown ${risk.cooldown_bars} bars` : null
  ].filter(Boolean);

  return parts.length ? parts.join(' · ') : '—';
}

function formatCoreOverlaySummary(coreOverlay: JsonRecord | null): string {
  if (!coreOverlay) return '—';

  const enabled = coreOverlay.enabled === true;
  if (!enabled) return 'Disabled';

  const coreAllocation =
    typeof coreOverlay.core_allocation_pct === 'number'
      ? coreOverlay.core_allocation_pct
      : null;

  if (coreAllocation === null) return 'Enabled';

  const overlayAllocation = Math.max(0, 1 - coreAllocation);
  return `${formatPercent(coreAllocation)} core · ${formatPercent(overlayAllocation)} overlay`;
}

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] items-start gap-3 border-b app-border-soft px-4 py-2.5 text-sm leading-snug last:border-b-0">
      <div className="app-text-soft">{label}</div>
      <div className="app-title break-words font-medium">{value || '—'}</div>
    </div>
  );
}
