import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { StateCard } from '../components/shared/StateCard';
import { createStrategyVersion, fetchStrategyDashboard, fetchSweepVariantDetail } from '../lib/api';
import { formatRankingMetricName, isRecord, toNumber } from '../lib/sweepVariants';
import type {
  CreateStrategyVersionRequest,
  StrategyDashboardResponse,
  StrategyVersionSummary,
  SweepVariantDetailResponse
} from '../types/api';

type CreateStrategyVersionLocationState = {
  builderDraft?: {
    configText?: string;
    changeNote?: string;
    sourceLabel?: string;
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

function removeEditableIdentityFields(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  const editable = { ...(value as Record<string, unknown>) };
  delete editable.name;
  return editable;
}

function editableConfigText(value: unknown): string {
  return prettifyJson(removeEditableIdentityFields(value));
}

function editableConfigTextFromString(value: string): string {
  try {
    return editableConfigText(JSON.parse(value));
  } catch {
    return value;
  }
}

function shortRunId(runId: string): string {
  return runId.split('-')[0] || runId;
}

function findRequestedVersion(
  versions: StrategyVersionSummary[],
  versionId: string | null,
  versionNumberParam: string | null
): StrategyVersionSummary | null {
  if (versionId) {
    const version = versions.find((item) => item.id === versionId);
    return version ?? null;
  }

  if (versionNumberParam) {
    const versionNumber = Number(versionNumberParam);
    if (Number.isInteger(versionNumber)) {
      const version = versions.find((item) => item.version_number === versionNumber);
      if (version) return version;
    }
  }

  return null;
}

function rankingValue(row: Record<string, unknown>, metric: string): number {
  const value = toNumber(row[metric]);
  if (value === null) return Number.NEGATIVE_INFINITY;
  if (metric === 'max_drawdown_pct') {
    return value <= 0 ? value : -value;
  }
  return value;
}

function rankForMetric(response: SweepVariantDetailResponse, variantId: string, metric: string): number {
  const results = response.run.summary_json?.results;
  const rows = Array.isArray(results) ? results.filter(isRecord) : [];
  const ranked = rows.sort((left, right) => rankingValue(right, metric) - rankingValue(left, metric));
  const index = ranked.findIndex((row) => row.variant_id === variantId);
  return index === -1 ? response.rank : index + 1;
}

const strategyTypeLabels: Record<string, string> = {
  SINGLE_ASSET: 'Single ETF',
  SIMULATION: 'Single ETF',
  PORTFOLIO: 'Portfolio',
  COMPARISON: 'Comparison',
  PARAMETER_SWEEP: 'Parameter Sweep'
};

function formatStrategyType(strategyType: string | null | undefined): string {
  if (!strategyType) return 'Strategy';

  return (
    strategyTypeLabels[strategyType] ??
    strategyType
      .toLowerCase()
      .split('_')
      .filter(Boolean)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  );
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
  const [searchParams] = useSearchParams();

  const builderDraft =
    (location.state as CreateStrategyVersionLocationState | null)?.builderDraft ?? null;
  const sweepRunId = searchParams.get('sweepRunId');
  const sweepVariantId = searchParams.get('variantId');
  const sweepRankingMetric = searchParams.get('rankingMetric');
  const requestedSourceVersionId = searchParams.get('fromVersionId') ?? searchParams.get('versionId');
  const requestedSourceVersionNumber = searchParams.get('fromVersion') ?? searchParams.get('version');

  const [strategyDashboard, setStrategyDashboard] = useState<StrategyDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [changeNote, setChangeNote] = useState(builderDraft?.changeNote ?? '');
  const [configText, setConfigText] = useState('{}');

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const inputClassName =
    'app-version-input w-full rounded-2xl px-4 py-3 text-sm outline-none transition';
  const textareaClassName =
    'app-json-editor min-h-[460px] w-full rounded-2xl px-4 py-3 font-mono text-sm leading-6 outline-none transition';

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
        const sourceVersion =
          findRequestedVersion(response.versions, requestedSourceVersionId, requestedSourceVersionNumber) ??
          currentVersion;

        if (builderDraft?.configText) {
          setConfigText(editableConfigTextFromString(builderDraft.configText));
          if (builderDraft.changeNote) {
            setChangeNote(builderDraft.changeNote);
          }
          return;
        }

        if (sweepRunId && sweepVariantId) {
          const variantResponse = await fetchSweepVariantDetail(sweepRunId, sweepVariantId);
          if (!active) return;

          if (strategyId && variantResponse.run.strategy_id !== strategyId) {
            setLoadError('Sweep variant does not belong to this strategy.');
            return;
          }

          setConfigText(editableConfigText(variantResponse.variant.config ?? {}));
          const rankingMetric = sweepRankingMetric || variantResponse.ranking_metric || 'sharpe_ratio';
          const rank = rankForMetric(variantResponse, sweepVariantId, rankingMetric);
          setChangeNote(
            `Promoted from parameter sweep result ${shortRunId(sweepRunId)}, rank #${rank} by ${formatRankingMetricName(rankingMetric)}.`
          );
          return;
        }

        setConfigText(editableConfigText(sourceVersion?.config_json ?? {}));
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
  }, [
    builderDraft?.changeNote,
    builderDraft?.configText,
    requestedSourceVersionId,
    requestedSourceVersionNumber,
    strategyId,
    sweepRankingMetric,
    sweepRunId,
    sweepVariantId
  ]);

  const currentVersion = useMemo<StrategyVersionSummary | null>(() => {
    if (!strategyDashboard) return null;
    return (
      strategyDashboard.versions.find((version) => version.is_current) ??
      strategyDashboard.versions[0] ??
      null
    );
  }, [strategyDashboard]);

  const sourceVersion = useMemo<StrategyVersionSummary | null>(() => {
    if (!strategyDashboard) return null;
    return (
      findRequestedVersion(strategyDashboard.versions, requestedSourceVersionId, requestedSourceVersionNumber) ??
      currentVersion
    );
  }, [currentVersion, requestedSourceVersionId, requestedSourceVersionNumber, strategyDashboard]);

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

      parsedConfig = removeEditableIdentityFields(parsed);
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
      const response = await createStrategyVersion(strategyId, payload);
      navigate(`/strategies/${strategyId}?versionId=${response.version_id}`, {
        state: {
          notice: {
            tone: 'success',
            message: 'New version saved. Run this version to create its reference result.'
          }
        }
      });
    } catch (error) {
      setSubmitError(normalizeError(error));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-10">
        <StateCard
          title="Loading version workspace"
          description="Fetching the current strategy before preparing the version editor."
        />
      </div>
    );
  }

  if (loadError || !strategyDashboard) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-10">
        <StateCard
          title="Unable to load strategy"
          description={loadError ?? 'Strategy dashboard was not available.'}
          tone="error"
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="app-eyebrow text-xs font-semibold uppercase tracking-[0.28em]">
            Advanced Versioning
          </div>
          <h1 className="app-title mt-2 text-3xl font-semibold tracking-tight">
            New Version · {strategyDashboard.strategy.name}
          </h1>
          <p className="app-text-muted mt-3 max-w-3xl text-sm">
            Create a saved version when you want to preserve a meaningful strategy change.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to={`/strategies/${strategyDashboard.strategy.id}${sourceVersion ? `?versionId=${sourceVersion.id}` : ''}`}
            className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition"
          >
            Back to Strategy
          </Link>
        </div>
      </div>

      {builderDraft && (
        <div className="app-note mb-6 rounded-2xl border px-4 py-3 text-sm">
          Prefilled from {builderDraft.sourceLabel ?? 'Strategy Builder'}. Review the structured draft before saving it as a new version.
        </div>
      )}

      {!builderDraft && sweepRunId && sweepVariantId ? (
        <div className="app-note mb-6 rounded-2xl border px-4 py-3 text-sm">
          Prefilled from parameter sweep variant. Review and edit before saving it as a new version.
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.85fr)]">
        <form
          onSubmit={handleSubmit}
          className="app-card app-shadow rounded-3xl border p-6"
        >
          <div className="mb-6">
            <h2 className="app-title text-xl font-semibold">Version Details</h2>
            <p className="app-text-muted mt-2 text-sm">
              Add a short change note and review the strategy config before saving.
            </p>
          </div>

          <div className="grid gap-5">
            <Field label="Change Note">
              <input
                type="text"
                value={changeNote}
                onChange={(event) => setChangeNote(event.target.value)}
                placeholder="Example: changed RSI entry threshold from 30 to 25"
                className={inputClassName}
              />
              <span className="app-text-soft text-xs">
                Optional, but useful for tracking why this version was created.
              </span>
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
            <div className="app-validation-error mt-6 rounded-2xl px-4 py-3 text-sm">
              {submitError}
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="app-button-primary rounded-2xl px-5 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Saving Version...' : 'Save New Version'}
            </button>

            <button
              type="button"
              onClick={() =>
                setConfigText(
                  builderDraft?.configText
                    ? editableConfigTextFromString(builderDraft.configText)
                    : editableConfigText(sourceVersion?.config_json ?? {})
                )
              }
              className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-medium transition"
            >
              {builderDraft ? 'Reset to Builder Draft' : 'Reset to Starting Version'}
            </button>
          </div>
        </form>

        <div className="space-y-6">
          <section className="app-card app-shadow rounded-3xl border p-6">
            <h2 className="app-title text-xl font-semibold">Version Context</h2>
            <p className="app-text-muted mt-2 text-sm">
              This strategy will keep its history and mark the new version as current.
            </p>

            <div className="mt-5 space-y-3">
              <PreviewRow label="Strategy" value={strategyDashboard.strategy.name} />
              <PreviewRow
                label="Starting Version"
                value={sourceVersion ? `v${sourceVersion.version_number}` : '—'}
              />
              <PreviewRow
                label="Strategy Type"
                value={formatStrategyType(strategyDashboard.strategy.strategy_type)}
              />
              <PreviewRow label="Starting Change Note" value={sourceVersion?.change_note ?? '—'} />
            </div>
          </section>

          <section className="app-card app-shadow rounded-3xl border p-6">
            <h2 className="app-title text-xl font-semibold">Starting Version Snapshot</h2>
            <p className="app-text-muted mt-2 text-sm">
              Read-only reference for the version you are starting from.
            </p>

            <pre className="app-code-block app-title mt-5 max-h-[460px] overflow-auto rounded-2xl p-4 text-xs leading-6">
              {prettifyJson(sourceVersion?.config_json ?? {})}
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
    <div className="app-surface-soft rounded-2xl border px-4 py-4">
      <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
        {label}
      </div>
      <div className="app-title mt-2 break-words text-sm">{value || '—'}</div>
    </div>
  );
}
