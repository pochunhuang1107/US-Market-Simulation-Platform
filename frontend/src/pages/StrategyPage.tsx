import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { VersionsTable } from '../components/strategy/VersionsTable';
import { RunsTable } from '../components/runs/RunsTable';
import { MetricCard } from '../components/shared/MetricCard';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { archiveStrategy, fetchStrategyDashboard, restoreStrategy } from '../lib/api';
import { formatDateTime, formatPct } from '../lib/formatters';
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

export function StrategyPage() {
  const { strategyId } = useParams();
  const [data, setData] = useState<StrategyDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusActionLoading, setStatusActionLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [statusActionError, setStatusActionError] = useState<string | null>(null);

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

  const latestMetrics = useMemo(() => {
    const latest = data?.latest_performance;
    if (!latest) return [];

    return [
      { label: 'Latest Total Return', value: formatPct(latest.total_return_pct) },
      { label: 'Latest Benchmark Return', value: formatPct(latest.benchmark_return_pct) },
      {
        label: 'Latest Alpha',
        value: formatPct(latest.alpha_vs_benchmark_pct),
        tone: (latest.alpha_vs_benchmark_pct ?? 0) >= 0 ? ('positive' as const) : ('negative' as const)
      },
      { label: 'Latest CAGR', value: formatPct(latest.cagr_pct) }
    ];
  }, [data]);

  const currentVersion = useMemo(() => {
    if (!data) return null;
    return data.versions.find((version) => version.is_current) ?? data.versions[0] ?? null;
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

  if (loading) {
    return <StateCard title="Loading strategy dashboard" description="Fetching strategy metadata, versions, and associated runs." />;
  }

  if (errorMessage || !data) {
    return <StateCard title="Unable to load strategy" description={errorMessage ?? 'Strategy dashboard was not available.'} tone="error" />;
  }

  return (
    <div className="space-y-6">
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

      <section className="app-card app-shadow-soft rounded-3xl border p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
              Next strategy steps
            </div>
            <p className="app-text-muted mt-2 text-sm leading-6">
              Keep iterating from the saved version or review recent results.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {data.latest_run_id ? (
              <Link
                to={`/runs/${data.latest_run_id}`}
                className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Open latest run
              </Link>
            ) : null}
            {data.latest_run_id ? (
              <Link
                to={`/compare?runIds=${data.latest_run_id}`}
                className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Compare latest run
              </Link>
            ) : null}
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
        <SectionCard title="Strategy Info" subtitle="Saved strategy context and recent activity.">
          <dl className="space-y-4 text-sm">
            <Row label="Type" value={formatStrategyType(data.strategy.strategy_type)} />
            <Row label="Created" value={formatDateTime(data.strategy.created_at)} />
            <Row label="Updated" value={formatDateTime(data.strategy.updated_at)} />
            <Row label="Total runs" value={String(data.total_runs)} />
            <Row label="Latest finished at" value={formatDateTime(data.latest_finished_at)} />
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

        <SectionCard title="Latest Performance" subtitle="Most recent succeeded run summary for this strategy.">
          {data.latest_performance ? (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                {latestMetrics.map((metric) => (
                  <MetricCard key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
                ))}
              </div>
              {data.latest_run_id ? (
                <Link to={`/runs/${data.latest_run_id}`} className="app-button-secondary inline-flex rounded-xl px-4 py-2 text-sm transition">
                  Open latest run
                </Link>
              ) : null}
            </div>
          ) : (
            <p className="app-text-muted text-sm">No succeeded run is available yet for this strategy.</p>
          )}
        </SectionCard>
      </div>

      <SectionCard title="Versions" subtitle="Strategy version history with current version highlighting.">
        <VersionsTable versions={data.versions} />
      </SectionCard>

      <SectionCard title="Associated Runs" subtitle="Recent runs associated with this strategy.">
        <RunsTable runs={data.associated_runs} loading={false} compact />
      </SectionCard>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div className="app-code flex flex-col gap-1 rounded-2xl border px-4 py-3">
      <span className="app-label text-xs font-semibold uppercase tracking-[0.18em]">{label}</span>
      <span className={`${mono ? 'font-mono text-xs break-all' : ''} app-title`}>{value || '—'}</span>
    </div>
  );
}
