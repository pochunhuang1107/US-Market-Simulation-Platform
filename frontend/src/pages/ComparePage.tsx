import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { ComparisonInsightSummary } from '../components/compare/ComparisonInsightSummary';
import { CurveChart, pctFormatter } from '../components/compare/CurveChart';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchRunComparison, fetchRunComparisonChart, fetchRunsDashboard } from '../lib/api';
import { formatNumber, formatPct, formatRunLabel } from '../lib/formatters';
import type { RunComparisonChartResponse, RunComparisonResponse, RunDashboardListItem } from '../types/api';

function parseRunIdsParam(value: string | null): string[] {
  if (!value) return [];

  return Array.from(
    new Set(
      value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    )
  ).slice(0, 6);
}

export function ComparePage() {
  const [searchParams] = useSearchParams();
  const initialSelectedRunIds = useMemo(
    () => parseRunIdsParam(searchParams.get('runIds')),
    [searchParams]
  );
  const autoCompareKeyRef = useRef<string | null>(null);

  const [availableRuns, setAvailableRuns] = useState<RunDashboardListItem[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>(initialSelectedRunIds);
  const [comparison, setComparison] = useState<RunComparisonResponse | null>(null);
  const [comparisonChart, setComparisonChart] = useState<RunComparisonChartResponse | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (initialSelectedRunIds.length >= 2) {
      setSelectedRunIds(initialSelectedRunIds);
    }
  }, [initialSelectedRunIds]);

  useEffect(() => {
    let ignore = false;

    async function loadRuns() {
      setLoadingRuns(true);
      try {
        const response = await fetchRunsDashboard({ status: 'SUCCEEDED', page: 1, page_size: 100, sort_by: 'finished_at', sort_order: 'desc' });
        if (!ignore) {
          setAvailableRuns(response.items);
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load comparable runs');
        }
      } finally {
        if (!ignore) {
          setLoadingRuns(false);
        }
      }
    }

    void loadRuns();
    return () => {
      ignore = true;
    };
  }, []);

  const selectedRuns = useMemo(
    () => availableRuns.filter((run) => selectedRunIds.includes(run.run_id)),
    [availableRuns, selectedRunIds]
  );

  async function handleCompare(runIdsOverride?: string[]) {
    const runIds = runIdsOverride ?? selectedRunIds;

    if (runIds.length < 2) {
      setErrorMessage('Select at least two succeeded runs to compare.');
      return;
    }

    setLoadingComparison(true);
    setErrorMessage(null);

    try {
      const [summary, chart] = await Promise.all([
        fetchRunComparison(runIds),
        fetchRunComparisonChart(runIds)
      ]);
      setComparison(summary);
      setComparisonChart(chart);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to compare runs');
      setComparison(null);
      setComparisonChart(null);
    } finally {
      setLoadingComparison(false);
    }
  }

  useEffect(() => {
    if (initialSelectedRunIds.length < 2) return;

    const compareKey = initialSelectedRunIds.join(',');
    if (autoCompareKeyRef.current === compareKey) return;

    autoCompareKeyRef.current = compareKey;
    void handleCompare(initialSelectedRunIds);
  }, [initialSelectedRunIds]);

  function toggleRun(runId: string) {
    setSelectedRunIds((current) =>
      current.includes(runId) ? current.filter((value) => value !== runId) : [...current, runId].slice(-6)
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Compare"
        title="Run Comparison Workspace"
        description="Select multiple succeeded runs, then compare normalized strategy curves, benchmark curves, and drawdown series."
        actions={
          <button
            type="button"
            onClick={() => {
              void handleCompare();
            }}
            disabled={loadingComparison || selectedRunIds.length < 2}
            className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loadingComparison ? 'Comparing…' : 'Compare selected runs'}
          </button>
        }
      />

      {errorMessage ? <StateCard title="Comparison issue" description={errorMessage} tone="error" /> : null}

      {comparison ? <ComparisonInsightSummary comparison={comparison} /> : null}

      {comparison ? (
        <SectionCard title="Comparison Summary" subtitle="Metric summary for the selected runs.">
          <div className="app-table overflow-auto rounded-2xl border">
            <table className="min-w-full divide-y app-divider text-sm">
              <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
                <tr>
                  <th className="px-4 py-3">Run</th>
                  <th className="px-4 py-3">Total Return</th>
                  <th className="px-4 py-3">Alpha</th>
                  <th className="px-4 py-3">CAGR</th>
                  <th className="px-4 py-3">Sharpe</th>
                  <th className="px-4 py-3">Max DD</th>
                </tr>
              </thead>
              <tbody className="divide-y app-divider">
                {comparison.runs.map((run) => (
                  <tr key={run.run_id} className="app-row-hover">
                    <td className="px-4 py-3 font-medium app-title">
                      {formatRunLabel(run.strategy_name, run.strategy_version_number)}
                    </td>
                    <td className="px-4 py-3 app-text-muted">{formatPct(run.total_return_pct)}</td>
                    <td className="px-4 py-3 app-text-muted">{formatPct(run.alpha_vs_benchmark_pct)}</td>
                    <td className="px-4 py-3 app-text-muted">{formatPct(run.cagr_pct)}</td>
                    <td className="px-4 py-3 app-text-muted">{formatNumber(run.sharpe_ratio)}</td>
                    <td className="px-4 py-3 app-text-muted">{formatPct(run.max_drawdown_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      ) : null}

      {comparisonChart ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <CurveChart
            title="Strategy Curves"
            subtitle="Normalized strategy equity curves for the selected runs."
            curves={comparisonChart.strategy_curves}
          />
          <CurveChart
            title="Benchmark Curves"
            subtitle="Normalized benchmark equity curves for the same runs."
            curves={comparisonChart.benchmark_curves}
          />
          <CurveChart
            title="Strategy Drawdowns"
            subtitle="Strategy drawdown overlays for selected runs."
            curves={comparisonChart.strategy_drawdown_curves}
            yFormatter={pctFormatter}
            zeroLine
          />
          <CurveChart
            title="Benchmark Drawdowns"
            subtitle="Benchmark drawdown overlays for selected runs."
            curves={comparisonChart.benchmark_drawdown_curves}
            yFormatter={pctFormatter}
            zeroLine
          />
        </div>
      ) : null}

      <SectionCard title="Selected Runs" subtitle="Choose at least two succeeded runs. Latest selections are kept if you go over the cap.">
        {selectedRuns.length === 0 ? (
          <p className="text-sm app-text-muted">No runs selected yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {selectedRuns.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => toggleRun(run.run_id)}
                className="app-badge rounded-full px-3 py-1.5 text-xs font-medium"
              >
                {formatRunLabel(run.strategy_name, run.strategy_version_number)}
              </button>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Succeeded Runs" subtitle="Recent finished runs available for comparison.">
        <div className="app-table overflow-auto rounded-2xl border">
          <table className="min-w-full divide-y app-divider text-sm">
            <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
              <tr>
                <th className="px-4 py-3">Pick</th>
                <th className="px-4 py-3">Run</th>
                <th className="px-4 py-3">Return</th>
                <th className="px-4 py-3">Sharpe</th>
                <th className="px-4 py-3">Max DD</th>
              </tr>
            </thead>
            <tbody className="divide-y app-divider">
              {loadingRuns ? (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center app-text-muted">
                    Loading succeeded runs…
                  </td>
                </tr>
              ) : (
                availableRuns.map((run) => {
                  const checked = selectedRunIds.includes(run.run_id);
                  return (
                    <tr key={run.run_id} className="app-row-hover">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleRun(run.run_id)}
                          className="app-checkbox h-4 w-4 rounded"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium app-title">
                          {formatRunLabel(run.strategy_name, run.strategy_version_number)}
                        </div>
                        <div className="mt-1 font-mono text-xs app-text-soft">{run.run_id}</div>
                      </td>
                      <td className="px-4 py-3 app-text-muted">{formatPct(run.total_return_pct)}</td>
                      <td className="px-4 py-3 app-text-muted">{formatNumber(run.sharpe_ratio)}</td>
                      <td className="px-4 py-3 app-text-muted">{formatPct(run.max_drawdown_pct)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}