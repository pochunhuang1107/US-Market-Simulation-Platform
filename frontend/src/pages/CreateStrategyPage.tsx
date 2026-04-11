import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { createStrategy } from '../lib/api';
import type { CreateStrategyRequest } from '../types/api';

const DEFAULT_CONFIG = `{
  "name": "qqq-rsi-test",
  "tradable_symbol": "QQQ",
  "benchmark_symbol": "QQQ",
  "start_date": "2018-01-02",
  "end_date": "2024-12-31",
  "initial_capital": 100000,
  "transaction_cost_bps": 5,
  "core_allocation_pct": 0.6,
  "overlay_allocation_pct": 0.4,
  "entry_rule": {
    "type": "group",
    "operator": "AND",
    "rules": [
      {
        "type": "indicator_threshold",
        "indicator": "rsi_14",
        "operator": "below",
        "value": 35
      }
    ]
  },
  "exit_rule": {
    "type": "indicator_threshold",
    "indicator": "rsi_14",
    "operator": "above",
    "value": 60
  }
}`;

const STRATEGY_TYPE_OPTIONS = [
  { value: 'SIMULATION', label: 'SIMULATION' },
  { value: 'PORTFOLIO', label: 'PORTFOLIO' },
  { value: 'COMPARISON', label: 'COMPARISON' },
  { value: 'PARAMETER_SWEEP', label: 'PARAMETER_SWEEP' }
] as const;

type CreateStrategyLocationState = {
  builderDraft?: {
    name?: string;
    description?: string;
    strategyType?: string;
    configText?: string;
  };
};

function normalizeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}

function prettifyJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
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
      <span className="text-xs font-semibold uppercase tracking-[0.22em] app-text-muted">
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

  const inputClassName =
    'app-form-field w-full rounded-2xl px-4 py-3 text-sm outline-none transition';
  const textareaClassName =
    'app-form-code min-h-[420px] w-full rounded-2xl px-4 py-3 font-mono text-sm outline-none transition';

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
          <div className="text-xs font-semibold uppercase tracking-[0.28em] app-accent">
            Us Market Strategy Platform
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight app-title">
            Create Strategy
          </h1>
          <p className="mt-3 max-w-3xl text-sm app-text-muted">
            Create a new strategy and its initial version using the existing backend contract.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to="/runs"
            className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition"
          >
            Back to Runs
          </Link>
        </div>
      </div>

      {builderDraft && (
        <div className="app-note mb-6 rounded-2xl px-4 py-3 text-sm">
          Prefilled from Strategy Builder. Review the draft and save when ready.
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.85fr)]">
        <form
          onSubmit={handleSubmit}
          className="rounded-3xl border app-divider app-card p-6 shadow-2xl "
        >
          <div className="mb-6">
            <h2 className="text-xl font-semibold app-title">Strategy Request</h2>
            <p className="mt-2 text-sm app-text-muted">
              This will create the strategy and automatically create version 1.
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
                  className="app-form-field min-h-[110px] w-full rounded-2xl px-4 py-3 text-sm outline-none transition"
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
            <div className="mt-6 rounded-2xl border border-rose-300/50 bg-rose-50/90 px-4 py-3 text-sm text-rose-900 dark:border-rose-900/70 dark:bg-rose-950/20 dark:text-rose-100">
              {submitError}
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
          <section className="rounded-3xl border app-divider app-card p-6 shadow-2xl ">
            <h2 className="text-xl font-semibold app-title">Live Preview</h2>
            <p className="mt-2 text-sm app-text-muted">
              Review the values that will be submitted to POST /strategies.
            </p>

            <div className="mt-5 space-y-3">
              <div className="app-value-block rounded-2xl px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.22em] app-text-soft">
                  Name
                </div>
                <div className="mt-2 text-sm app-title">{name || '—'}</div>
              </div>

              <div className="app-value-block rounded-2xl px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.22em] app-text-soft">
                  Strategy Type
                </div>
                <div className="mt-2 text-sm app-title">{strategyType}</div>
              </div>

              <div className="app-value-block rounded-2xl px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.22em] app-text-soft">
                  Description
                </div>
                <div className="mt-2 whitespace-pre-wrap text-sm app-title">
                  {description || '—'}
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-3xl border app-divider app-card p-6 shadow-2xl ">
            <h2 className="text-xl font-semibold app-title">Config Snapshot</h2>
            <p className="mt-2 text-sm app-text-muted">
              Read-only preview of the config JSON to be saved as version 1.
            </p>

            <pre className="app-form-code mt-5 max-h-[460px] overflow-auto rounded-2xl p-4 text-xs leading-6">
              {prettifyJson(configText)}
            </pre>
          </section>
        </div>
      </div>
    </div>
  );
}