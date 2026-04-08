import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';

import { RunCharts } from '../components/run-detail/RunCharts';
import { RunHeader } from '../components/run-detail/RunHeader';
import { RunMetaPanel } from '../components/run-detail/RunMetaPanel';
import { MetricCard } from '../components/shared/MetricCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchRunDashboard } from '../lib/api';
import { formatCurrency, formatDecimal, formatNumber, formatPct } from '../lib/formatters';
import type { RunDashboardResponse } from '../types/api';

export function RunDetailPage() {
  const { runId } = useParams();
  const [data, setData] = useState<RunDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadRunDashboard() {
      if (!runId) {
        setErrorMessage('Missing run id');
        setLoading(false);
        return;
      }

      setLoading(true);
      setErrorMessage(null);

      try {
        const response = await fetchRunDashboard(runId);
        if (!ignore) {
          setData(response);
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load run dashboard');
          setData(null);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    void loadRunDashboard();

    return () => {
      ignore = true;
    };
  }, [runId]);

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
    return <StateCard title="Loading run dashboard" description="Fetching run metadata and chart data from the backend." />;
  }

  if (errorMessage || !data) {
    return <StateCard title="Unable to load run dashboard" description={errorMessage ?? 'Run dashboard was not available.'} tone="error" />;
  }

  return (
    <div className="space-y-6">
      <RunHeader run={data.run} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {summaryMetrics.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
        ))}
      </div>

      <RunMetaPanel run={data.run} />
      <RunCharts chartData={data.chart_data} />
    </div>
  );
}
