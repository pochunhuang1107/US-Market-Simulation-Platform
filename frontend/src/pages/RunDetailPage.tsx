import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';

import { RunCharts } from '../components/run-detail/RunCharts';
import { RunHeader } from '../components/run-detail/RunHeader';
import { RunMetaPanel } from '../components/run-detail/RunMetaPanel';
import { MetricCard } from '../components/shared/MetricCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchRun, fetchRunDashboard, saveDraftRunAsStrategy } from '../lib/api';
import { formatCurrency, formatDecimal, formatNumber, formatPct } from '../lib/formatters';
import type { RunDashboardResponse, RunResponse } from '../types/api';

const ACTIVE_RUN_STATUSES = new Set(['PENDING', 'QUEUED', 'RUNNING']);
const POLL_INTERVAL_MS = 2000;

export function RunDetailPage() {
  const { runId } = useParams();

  const [run, setRun] = useState<RunResponse | null>(null);
  const [data, setData] = useState<RunDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [isSavingDraftStrategy, setIsSavingDraftStrategy] = useState(false);

  useEffect(() => {
    let ignore = false;
    let timeoutId: number | undefined;

    async function load() {
      if (!runId) {
        setErrorMessage('Missing run id');
        setLoading(false);
        return;
      }

      try {
        const runResponse = await fetchRun(runId);
        if (ignore) return;

        setRun(runResponse);

        if (runResponse.status === 'SUCCEEDED') {
          setIsFinalizing(true);
          setLoading(false);
          setErrorMessage(null);

          try {
            const dashboardResponse = await fetchRunDashboard(runId);
            if (ignore) return;

            setData(dashboardResponse);
            setIsFinalizing(false);
            setErrorMessage(null);
            setLoading(false);
            return;
          } catch {
            if (ignore) return;

            setData(null);
            setIsFinalizing(true);
            setErrorMessage(null);
            setLoading(false);

            timeoutId = window.setTimeout(() => {
              void load();
            }, POLL_INTERVAL_MS);

            return;
          }
        }

        if (runResponse.status === 'FAILED' || runResponse.status === 'CANCELLED') {
          setData(null);
          setIsFinalizing(false);
          setErrorMessage(runResponse.error_message ?? `Run ${runResponse.status.toLowerCase()}.`);
          setLoading(false);
          return;
        }

        if (ACTIVE_RUN_STATUSES.has(runResponse.status)) {
          setData(null);
          setIsFinalizing(false);
          setErrorMessage(null);
          setLoading(false);

          timeoutId = window.setTimeout(() => {
            void load();
          }, POLL_INTERVAL_MS);

          return;
        }

        setData(null);
        setIsFinalizing(false);
        setErrorMessage(`Unsupported run status: ${runResponse.status}`);
        setLoading(false);
      } catch (error) {
        if (ignore) return;
        setData(null);
        setIsFinalizing(false);
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load run');
        setLoading(false);
      }
    }

    setLoading(true);
    setErrorMessage(null);
    setRun(null);
    setData(null);
    setIsFinalizing(false);
    void load();

    return () => {
      ignore = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [runId]);

  async function handleSaveDraftStrategy() {
    if (!runId || !run) return;
    if (run.strategy_id) return;

    const suggestedName =
      typeof run.request_payload?.draft_config === 'object' &&
      run.request_payload?.draft_config &&
      typeof (run.request_payload.draft_config as Record<string, unknown>).name === 'string'
        ? ((run.request_payload.draft_config as Record<string, unknown>).name as string)
        : 'My strategy';

    const name = window.prompt('Enter a name for this strategy', suggestedName)?.trim();
    if (!name) return;

    setIsSavingDraftStrategy(true);

    try {
      await saveDraftRunAsStrategy(runId, {
        name,
        description: `Saved from run ${runId}`,
        strategy_type: 'SINGLE_ASSET'
      });

      const refreshedRun = await fetchRun(runId);
      setRun(refreshedRun);
      window.alert('Strategy saved successfully.');
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Failed to save strategy');
    } finally {
      setIsSavingDraftStrategy(false);
    }
  }

  const summaryMetrics = useMemo(() => {
    const summary = data?.run.summary_json ?? {};
    const toNumber = (value: unknown): number | null => (typeof value === 'number' ? value : null);

    return [
      { label: 'Ending Equity', value: formatCurrency(toNumber(summary['ending_equity'])) },
      {
        label: 'Total Return',
        value: formatPct(toNumber(summary['total_return_pct'])),
        tone: (toNumber(summary['total_return_pct']) ?? 0) >= 0 ? ('positive' as const) : ('negative' as const)
      },
      { label: 'Benchmark Return', value: formatPct(toNumber(summary['benchmark_return_pct'])) },
      {
        label: 'Alpha vs Benchmark',
        value: formatPct(toNumber(summary['alpha_vs_benchmark_pct'])),
        tone: (toNumber(summary['alpha_vs_benchmark_pct']) ?? 0) >= 0 ? ('positive' as const) : ('negative' as const)
      },
      { label: 'CAGR', value: formatPct(toNumber(summary['cagr_pct'])) },
      { label: 'Sharpe Ratio', value: formatDecimal(toNumber(summary['sharpe_ratio'])) },
      {
        label: 'Max Drawdown',
        value: formatPct(toNumber(summary['max_drawdown_pct'])),
        tone: 'negative' as const
      },
      { label: 'Trades', value: formatNumber(toNumber(summary['trade_count'])) }
    ];
  }, [data]);

  if (loading) {
    return <StateCard title="Loading run" description="Fetching run status and dashboard data from the backend." />;
  }

  if (isFinalizing) {
    return (
      <div className="space-y-6">
        <StateCard
          title="Preparing simulation results"
          description="Your run has finished. Final charts and metrics are loading."
        />
        {run ? <RunMetaPanel run={run} /> : null}
      </div>
    );
  }

  if (run && ACTIVE_RUN_STATUSES.has(run.status)) {
    return (
      <div className="space-y-6">
        <StateCard
          title="Simulation in progress"
          description={
            run.progress_message
              ? `${run.progress_message} (${run.progress_pct}%)`
              : `Run status: ${run.status}. Waiting for completion...`
          }
        />
        <RunMetaPanel run={run} />
      </div>
    );
  }

  if (run && (run.status === 'FAILED' || run.status === 'CANCELLED')) {
    return (
      <div className="space-y-6">
        <StateCard
          title={`Run ${run.status.toLowerCase()}`}
          description={run.error_message ?? 'This run did not complete successfully.'}
          tone="error"
        />
        <RunMetaPanel run={run} />
      </div>
    );
  }

  if (errorMessage || !data) {
    return (
      <StateCard
        title="Unable to load run dashboard"
        description={errorMessage ?? 'Run dashboard was not available.'}
        tone="error"
      />
    );
  }

  return (
    <div className="space-y-6">
      {run ? (
        <RunHeader
          run={run}
          canSaveDraftStrategy={run.status === 'SUCCEEDED' && !run.strategy_id}
          isSavingDraftStrategy={isSavingDraftStrategy}
          onSaveDraftStrategy={() => {
            void handleSaveDraftStrategy();
          }}
        />
      ) : null}
      <RunCharts chartData={data.chart_data} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {summaryMetrics.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
        ))}
      </div>

      <RunMetaPanel run={data.run} />
    </div>
  );
}