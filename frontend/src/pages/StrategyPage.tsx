import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';

import { VersionsTable } from '../components/strategy/VersionsTable';
import { RunsTable } from '../components/runs/RunsTable';
import { MetricCard } from '../components/shared/MetricCard';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { archiveStrategy, createRun, enqueueRun, fetchStrategyDashboard, restoreStrategy } from '../lib/api';
import {
  formatDateTime,
  formatPct,
  formatSavedSweepVariantSource,
  isSavedSweepVariantResult
} from '../lib/formatters';
import type { StrategyDashboardResponse } from '../types/api';

function formatStrategyType(value: string | null | undefined) {
  if (!value) return 'Strategy';

  const labels: Record<string, string> = {
    SINGLE_ASSET: 'Single ETF',
    SIMULATION: 'Single ETF',
    PORTFOLIO: 'Portfolio',
    COMPARISON: 'Comparison',
    PARAMETER_SWEEP: 'Parameter Sweep'
  };

  if (labels[value]) return labels[value];

  return value
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function hasConfig(value: Record<string, unknown> | null | undefined) {
  return Boolean(value && Object.keys(value).length > 0);
}

type PageNotice = {
  tone: 'success' | 'info' | 'error';
  message: string;
};

export function StrategyPage() {
  const { strategyId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [data, setData] = useState<StrategyDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusActionLoading, setStatusActionLoading] = useState(false);
  const [runVersionLoading, setRunVersionLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [statusActionError, setStatusActionError] = useState<string | null>(null);
  const [runVersionError, setRunVersionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<PageNotice | null>(
    (location.state as { notice?: PageNotice } | null)?.notice ?? null
  );

  const loadStrategy = useCallback(
    async (shouldIgnore: () => boolean = () => false) => {
      if (!strategyId) {
        setLoading(false);
        setErrorMessage('Missing strategy id');
        return;
      }

      setErrorMessage(null);

      try {
        const response = await fetchStrategyDashboard(strategyId);
        if (!shouldIgnore()) {
          setData(response);
        }
      } catch (error) {
        if (!shouldIgnore()) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load strategy dashboard');
          setData(null);
        }
      } finally {
        if (!shouldIgnore()) {
          setLoading(false);
        }
      }
    },
    [strategyId]
  );

  useEffect(() => {
    let ignore = false;

    setLoading(true);
    void loadStrategy(() => ignore);
    return () => {
      ignore = true;
    };
  }, [loadStrategy]);

  const currentVersion = useMemo(() => {
    if (!data) return null;
    return data.versions.find((version) => version.is_current) ?? data.versions[0] ?? null;
  }, [data]);

  const referencePerformance = data?.reference_performance ?? null;
  const referenceRunId = data?.reference_run_id ?? currentVersion?.reference_run_id ?? null;
  const referenceFinishedAt = data?.reference_finished_at ?? referencePerformance?.finished_at ?? null;

  const referenceMetrics = useMemo(() => {
    const reference = data?.reference_performance;
    if (!reference) return [];

    return [
      { label: 'Reference Total Return', value: formatPct(reference.total_return_pct) },
      { label: 'Reference Benchmark Return', value: formatPct(reference.benchmark_return_pct) },
      {
        label: 'Reference Alpha',
        value: formatPct(reference.alpha_vs_benchmark_pct),
        tone: (reference.alpha_vs_benchmark_pct ?? 0) >= 0 ? ('positive' as const) : ('negative' as const)
      },
      { label: 'Reference CAGR', value: formatPct(reference.cagr_pct) }
    ];
  }, [data]);

  const currentConfig = currentVersion?.config_json ?? null;
  const strategyStatus = data?.strategy.status?.toUpperCase();
  const isArchived = strategyStatus === 'ARCHIVED';
  const isActive = strategyStatus === 'ACTIVE';
  const canContinueInChat = hasConfig(currentConfig);
  const chatState = canContinueInChat
    ? {
        source: 'strategy',
        sourceDraftConfig: currentConfig,
        prefillPrompt: `Create a draft variant of ${data?.strategy.name ?? 'this strategy'}.`
      }
    : undefined;
  const noticeClass =
    notice?.tone === 'error'
      ? 'app-alert-error'
      : notice?.tone === 'info'
        ? 'app-note'
        : 'app-alert-success';
  const referenceIsSavedSweepVariant = referencePerformance ? isSavedSweepVariantResult(referencePerformance) : false;

  async function handleStatusAction() {
    if (!strategyId || !data) return;

    if (isActive) {
      const confirmed = window.confirm('Archive this strategy? It will leave the active library, but versions and runs stay available.');
      if (!confirmed) return;
    }

    setStatusActionLoading(true);
    setStatusActionError(null);

    try {
      if (isArchived) {
        await restoreStrategy(strategyId);
      } else {
        await archiveStrategy(strategyId);
      }
      await loadStrategy();
    } catch (error) {
      setStatusActionError(error instanceof Error ? error.message : 'Failed to update strategy status');
    } finally {
      setStatusActionLoading(false);
    }
  }

  async function handleRunCurrentVersion() {
    if (!strategyId || !currentVersion) return;

    setRunVersionLoading(true);
    setRunVersionError(null);

    try {
      const requestPayload: Record<string, unknown> = {
        source: 'strategy_version_reference_run',
        set_as_reference_on_success: true,
        reference_strategy_version_id: currentVersion.id
      };
      if (typeof currentVersion.config_json.start_date === 'string') {
        requestPayload.start_date = currentVersion.config_json.start_date;
      }
      if (typeof currentVersion.config_json.end_date === 'string') {
        requestPayload.end_date = currentVersion.config_json.end_date;
      }

      const run = await createRun({
        strategy_id: strategyId,
        strategy_version_id: currentVersion.id,
        run_type: 'SIMULATION',
        executor_type: 'SIMULATION_EXECUTOR',
        request_payload: requestPayload,
        max_attempts: 1
      });
      await enqueueRun(run.id);
      navigate(`/runs/${run.id}`);
    } catch (error) {
      setRunVersionError(error instanceof Error ? error.message : 'Failed to run this version');
    } finally {
      setRunVersionLoading(false);
    }
  }

  if (loading) {
    return <StateCard title="Loading strategy dashboard" description="Fetching strategy metadata, versions, and associated runs." />;
  }

  if (errorMessage || !data) {
    return <StateCard title="Unable to load strategy" description={errorMessage ?? 'Strategy dashboard was not available.'} tone="error" />;
  }

  return (
    <div className="space-y-6">
      {notice ? (
        <div className={`${noticeClass} rounded-2xl border px-4 py-3 text-sm`}>
          <div className="flex items-start justify-between gap-4">
            <p>{notice.message}</p>
            <button
              type="button"
              onClick={() => setNotice(null)}
              className="text-xs font-semibold uppercase tracking-[0.2em] opacity-80 transition hover:opacity-100"
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      <PageHeader
        eyebrow="Strategy Library"
        title={data.strategy.name}
        description={data.strategy.description ?? 'No strategy description was provided.'}
        actions={
          <div className="flex items-center gap-3">
            <Link
              to="/strategies"
              className="app-button-secondary rounded-xl px-4 py-2 text-sm transition"
            >
              Back to Strategy Library
            </Link>
            {isActive || isArchived ? (
              <button
                type="button"
                onClick={() => void handleStatusAction()}
                disabled={statusActionLoading}
                className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isArchived ? 'Restore strategy' : 'Archive strategy'}
              </button>
            ) : null}
          </div>
        }
      />

      {statusActionError ? <StateCard title="Could not update strategy status" description={statusActionError} tone="error" /> : null}
      {runVersionError ? <StateCard title="Could not run version" description={runVersionError} tone="error" /> : null}

      <section className="app-card app-shadow-soft rounded-3xl border p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
              Continue Research
            </div>
            <p className="app-text-muted mt-2 text-sm leading-6">
              Open the current version's reference result, compare reference performance, or continue from the saved version in chat.
            </p>
            {referenceIsSavedSweepVariant && referencePerformance ? (
              <div className="app-note mt-3 inline-flex flex-wrap items-center gap-2 rounded-2xl border px-3 py-2 text-xs">
                <span>{formatSavedSweepVariantSource(referencePerformance)}</span>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {referenceRunId ? (
              <Link
                to={`/runs/${referenceRunId}`}
                className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Open reference result
              </Link>
            ) : (
              <span className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold opacity-60">
                Open reference result
              </span>
            )}
            {referenceRunId ? (
              <Link
                to={`/compare?runIds=${referenceRunId}`}
                className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Compare reference result
              </Link>
            ) : (
              <span className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold opacity-60">
                Compare reference result
              </span>
            )}
            {canContinueInChat ? (
              <Link
                to="/chat"
                state={chatState}
                className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Continue in Chat
              </Link>
            ) : null}
            <Link
              to={`/strategies/${data.strategy.id}/versions/new`}
              className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
            >
              New Version
            </Link>
          </div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <SectionCard title="Saved Strategy" subtitle="Core metadata and saved-strategy status.">
          <dl className="space-y-4 text-sm">
            <Row label="Type" value={formatStrategyType(data.strategy.strategy_type)} />
            <Row label="Created" value={formatDateTime(data.strategy.created_at)} />
            <Row label="Updated" value={formatDateTime(data.strategy.updated_at)} />
            <Row label="Total runs" value={String(data.total_runs)} />
            <Row label="Reference finished at" value={formatDateTime(referenceFinishedAt)} />
            <div className="flex flex-wrap gap-2 pt-1">
              <span className="app-surface-soft app-text-muted rounded-full border px-3 py-1 text-xs">
                {formatStrategyType(data.strategy.status)}
              </span>
              <span className="app-surface-soft app-text-muted rounded-full border px-3 py-1 text-xs">
                {formatStrategyType(data.strategy.visibility)}
              </span>
            </div>
          </dl>
        </SectionCard>

        <section className="app-card app-shadow-soft rounded-3xl border p-5 lg:p-6">
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="app-label text-xs font-semibold uppercase tracking-[0.22em]">Key Insight</p>
              <h3 className="app-title mt-2 text-xl font-semibold">Reference Performance</h3>
              <p className="app-text-muted mt-1 text-sm">Pinned result for the current saved strategy version.</p>
            </div>
          </div>
          {referencePerformance ? (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                {referenceMetrics.map((metric) => (
                  <MetricCard key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
                ))}
              </div>
            </div>
          ) : (
            <div className="app-surface-soft rounded-2xl border px-4 py-5">
              <p className="app-title text-sm font-semibold">No reference result yet</p>
              <p className="app-text-muted mt-2 text-sm">Run this version to create a reference result.</p>
              <button
                type="button"
                onClick={() => void handleRunCurrentVersion()}
                disabled={!currentVersion || runVersionLoading}
                className="app-button-primary mt-4 rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
              >
                {runVersionLoading ? 'Creating run...' : 'Run this version'}
              </button>
            </div>
          )}
        </section>
      </div>

      <SectionCard title="Versions" subtitle="Saved versions for this strategy. The current version is used for continuation and manual runs.">
        <VersionsTable versions={data.versions} />
      </SectionCard>

      <SectionCard title="Run History" subtitle="Recent simulations created from this saved strategy.">
        <RunsTable runs={data.associated_runs} loading={false} compact />
      </SectionCard>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div className="app-surface-soft flex flex-col gap-1 rounded-2xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <dt className="app-label text-xs font-semibold uppercase tracking-[0.18em]">{label}</dt>
      <dd className={`${mono ? 'font-mono text-xs break-all' : 'text-sm font-medium'} app-title sm:text-right`}>{value || '—'}</dd>
    </div>
  );
}
