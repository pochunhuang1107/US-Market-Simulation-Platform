import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';

import { createStrategyVersion, fetchStrategyDashboard } from '../lib/api';
import type {
  CreateStrategyVersionRequest,
  StrategyDashboardResponse,
  StrategyVersionSummary
} from '../types/api';

type CreateStrategyVersionLocationState = {
  builderDraft?: {
    configText?: string;
    changeNote?: string;
  };
};

function normalizeError(error: unknown): string {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error
  ) {
    const response = (error as {
      response?: { data?: { detail?: unknown } };
    }).response;

    const detail = response?.data?.detail;

    if (typeof detail === 'string') return detail;
    if (detail !== undefined) return JSON.stringify(detail);
  }

  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}

function prettifyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return '{}';
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
      <span className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
        {label}
      </span>
      {children}
    </label>
  );
}

export function CreateStrategyVersionPage() {
  const { strategyId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const builderDraft =
    (location.state as CreateStrategyVersionLocationState | null)?.builderDraft ?? null;

  const [strategyDashboard, setStrategyDashboard] = useState<StrategyDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [changeNote, setChangeNote] = useState(builderDraft?.changeNote ?? '');
  const [configText, setConfigText] = useState('{}');

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const inputClassName =
    'app-input w-full rounded-2xl px-4 py-3 text-sm outline-none transition focus:border-cyan-500';
  const textareaClassName =
    'app-code-block min-h-[460px] w-full rounded-2xl px-4 py-3 font-mono text-sm outline-none transition focus:border-cyan-500';

  useEffect(() => {
    let active = true;

    async function loadStrategy() {
      if (!strategyId) {
        setLoadError('Missing strategy id.');
        setLoading(false);
        return;
      }

      setLoading(true);
      setLoadError(null);

      try {
        const response = await fetchStrategyDashboard(strategyId);
        if (!active) return;

        setStrategyDashboard(response);

        const currentVersion =
          response.versions.find((version) => version.is_current) ?? response.versions[0] ?? null;

        setConfigText(
          builderDraft?.configText ?? prettifyJson(currentVersion?.config_json ?? {})
        );
      } catch (error) {
        if (!active) return;
        setLoadError(normalizeError(error));
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadStrategy();

    return () => {
      active = false;
    };
  }, [builderDraft?.configText, strategyId]);

  const currentVersion = useMemo<StrategyVersionSummary | null>(() => {
    if (!strategyDashboard) return null;
    return (
      strategyDashboard.versions.find((version) => version.is_current) ??
      strategyDashboard.versions[0] ??
      null
    );
  }, [strategyDashboard]);

  async function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);

    if (!strategyId) {
      setSubmitError('Missing strategy id.');
      return;
    }

    let parsedConfig: Record<string, unknown>;
    try {
      const parsed = JSON.parse(configText);

      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setSubmitError('Config must be a JSON object.');
        return;
      }

      parsedConfig = parsed as Record<string, unknown>;
    } catch {
      setSubmitError('Config must be valid JSON.');
      return;
    }

    const payload: CreateStrategyVersionRequest = {
      config: parsedConfig,
      change_note: changeNote.trim() || null
    };

    setSubmitting(true);

    try {
      await createStrategyVersion(strategyId, payload);
      navigate(`/strategies/${strategyId}`);
    } catch (error) {
      setSubmitError(normalizeError(error));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-10">
        <div className="app-card app-shadow rounded-3xl border p-8">
          Loading strategy version editor...
        </div>
      </div>
    );
  }

  if (loadError || !strategyDashboard) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-10">
        <div className="rounded-3xl border border-rose-900/60 bg-rose-950/40 p-8 text-rose-200">
          {loadError ?? 'Unable to load strategy.'}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="app-eyebrow text-xs font-semibold uppercase tracking-[0.28em]">
            Strategy Versioning
          </div>
          <h1 className="app-title mt-2 text-3xl font-semibold tracking-tight">
            New Version · {strategyDashboard.strategy.name}
          </h1>
          <p className="app-text-muted mt-3 max-w-3xl text-sm">
            Create a new version from the current strategy config, save a change note, and keep
            version history under the same strategy.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to={`/strategies/${strategyDashboard.strategy.id}`}
            className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition"
          >
            Back to Strategy
          </Link>
        </div>
      </div>

      {builderDraft && (
        <div className="app-note mb-6 rounded-2xl border px-4 py-3 text-sm">
          Prefilled from Strategy Builder. Review the draft and create the version when ready.
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.85fr)]">
        <form
          onSubmit={handleSubmit}
          className="app-card app-shadow rounded-3xl border p-6"
        >
          <div className="mb-6">
            <h2 className="app-title text-xl font-semibold">Version Request</h2>
            <p className="app-text-muted mt-2 text-sm">
              Start from the current version config and edit only what changed.
            </p>
          </div>

          <div className="grid gap-5">
            <Field label="Change Note">
              <input
                type="text"
                value={changeNote}
                onChange={(event) => setChangeNote(event.target.value)}
                placeholder="Adjusted RSI thresholds and exit rule"
                className={inputClassName}
              />
            </Field>

            <Field label="Config JSON">
              <textarea
                value={configText}
                onChange={(event) => setConfigText(event.target.value)}
                className={textareaClassName}
                spellCheck={false}
              />
            </Field>
          </div>

          {submitError && (
            <div className="mt-6 rounded-2xl border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
              {submitError}
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="app-button-primary rounded-2xl px-5 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Creating Version...' : 'Create Version'}
            </button>

            <button
              type="button"
              onClick={() =>
                setConfigText(
                  builderDraft?.configText ?? prettifyJson(currentVersion?.config_json ?? {})
                )
              }
              className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-medium transition"
            >
              {builderDraft ? 'Reset to Builder Draft' : 'Reset to Current Version'}
            </button>
          </div>
        </form>

        <div className="space-y-6">
          <section className="app-card app-shadow rounded-3xl border p-6">
            <h2 className="app-title text-xl font-semibold">Current Version</h2>
            <p className="app-text-muted mt-2 text-sm">
              The new version will be created under this strategy and become the current version.
            </p>

            <div className="mt-5 space-y-3">
              <PreviewRow label="Strategy" value={strategyDashboard.strategy.name} />
              <PreviewRow
                label="Current Version"
                value={currentVersion ? `v${currentVersion.version_number}` : '—'}
              />
              <PreviewRow label="Strategy Type" value={strategyDashboard.strategy.strategy_type} />
              <PreviewRow label="Current Change Note" value={currentVersion?.change_note ?? '—'} />
            </div>
          </section>

          <section className="app-card app-shadow rounded-3xl border p-6">
            <h2 className="app-title text-xl font-semibold">Current Config Snapshot</h2>
            <p className="app-text-muted mt-2 text-sm">
              Reference view of the current version config before saving the new one.
            </p>

            <pre className="app-code-block app-title mt-5 max-h-[460px] overflow-auto rounded-2xl p-4 text-xs leading-6">
              {prettifyJson(currentVersion?.config_json ?? {})}
            </pre>
          </section>
        </div>
      </div>
    </div>
  );
}

function PreviewRow({
  label,
  value
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="app-code rounded-2xl border px-4 py-4">
      <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
        {label}
      </div>
      <div className="app-title mt-2 break-words text-sm">{value || '—'}</div>
    </div>
  );
}