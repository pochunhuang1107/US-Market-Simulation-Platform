import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { VersionsTable } from '../components/strategy/VersionsTable';
import { RunsTable } from '../components/runs/RunsTable';
import { MetricCard } from '../components/shared/MetricCard';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchStrategyDashboard } from '../lib/api';
import { formatDateTime, formatPct } from '../lib/formatters';
import type { StrategyDashboardResponse } from '../types/api';

export function StrategyPage() {
  const { strategyId } = useParams();
  const [data, setData] = useState<StrategyDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadStrategy() {
      if (!strategyId) {
        setLoading(false);
        setErrorMessage('Missing strategy id');
        return;
      }

      try {
        const response = await fetchStrategyDashboard(strategyId);
        if (!ignore) {
          setData(response);
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load strategy dashboard');
          setData(null);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    void loadStrategy();
    return () => {
      ignore = true;
    };
  }, [strategyId]);

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

  if (loading) {
    return <StateCard title="Loading strategy dashboard" description="Fetching strategy metadata, versions, and associated runs." />;
  }

  if (errorMessage || !data) {
    return <StateCard title="Unable to load strategy" description={errorMessage ?? 'Strategy dashboard was not available.'} tone="error" />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Strategy"
        title={data.strategy.name}
        description={data.strategy.description ?? 'No strategy description was provided.'}
        actions={
          <div className="flex items-center gap-3">
            <Link
              to={`/strategies/${data.strategy.id}/versions/new`}
              className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition"
            >
              New Version
            </Link>
            <Link
              to="/strategy-builder"
              state={{
                builderContext: {
                  strategyId: data.strategy.id,
                  baseVersionId: currentVersion?.id ?? null,
                  currentConfig: currentVersion?.config_json ?? null
                }
              }}
              className="app-button-secondary rounded-xl px-4 py-2 text-sm transition"
            >
              Open in Builder
            </Link>
            <Link
              to="/runs"
              className="app-button-secondary rounded-xl px-4 py-2 text-sm transition"
            >
              Back to runs
            </Link>
          </div>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <SectionCard title="Strategy Info" subtitle="Core strategy metadata from GET /strategies/{id}/dashboard.">
          <dl className="space-y-4 text-sm">
            <Row label="Strategy ID" value={data.strategy.id} mono />
            <Row label="Type" value={data.strategy.strategy_type} />
            <Row label="Status" value={data.strategy.status} />
            <Row label="Visibility" value={data.strategy.visibility} />
            <Row label="Current version ID" value={data.strategy.current_version_id} mono />
            <Row label="Created at" value={formatDateTime(data.strategy.created_at)} />
            <Row label="Updated at" value={formatDateTime(data.strategy.updated_at)} />
            <Row label="Total runs" value={String(data.total_runs)} />
            <Row label="Latest finished at" value={formatDateTime(data.latest_finished_at)} />
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
    <div className="app-code rounded-2xl border px-4 py-3">
      <span className="app-label text-xs font-semibold uppercase tracking-[0.18em]">{label}</span>
      <span className={`${mono ? 'font-mono text-xs break-all' : ''} app-title`}>{value || '—'}</span>
    </div>
  );
}
