import { useEffect, useMemo, useState } from 'react';

import { CurveChart, pctFormatter } from '../components/compare/CurveChart';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchRunComparison, fetchRunComparisonChart, fetchRunsDashboard } from '../lib/api';
import { formatNumber, formatPct, formatRunLabel } from '../lib/formatters';
import type { RunComparisonChartResponse, RunComparisonResponse, RunDashboardListItem } from '../types/api';

export function ComparePage() {
  const [availableRuns, setAvailableRuns] = useState<RunDashboardListItem[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<RunComparisonResponse | null>(null);
  const [comparisonChart, setComparisonChart] = useState<RunComparisonChartResponse | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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

  async function handleCompare() {
    if (selectedRunIds.length < 2) {
      setErrorMessage('Select at least two succeeded runs to compare.');
      return;
    }

    setLoadingComparison(true);
    setErrorMessage(null);

    try {
      const [summary, chart] = await Promise.all([
        fetchRunComparison(selectedRunIds),
        fetchRunComparisonChart(selectedRunIds)
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
        description="Select multiple succeeded runs, then compare normalized strategy curves, benchmark curves, and drawdown series using the finalized split endpoints."
        actions={
          <button
            type="button"
            onClick={handleCompare}
            disabled={loadingComparison || selectedRunIds.length < 2}
            className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loadingComparison ? 'Comparing…' : 'Compare selected runs'}
          </button>
        }
      />

      {errorMessage ? <StateCard title="Comparison issue" description={errorMessage} tone="error" /> : null}

      <SectionCard title="Selected Runs" subtitle="Choose at least two succeeded runs. Latest selections are kept if you go over the cap.">
        {selectedRuns.length === 0 ? (
          <p className="text-sm text-slate-400">No runs selected yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {selectedRuns.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => toggleRun(run.run_id)}
                className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-300"
              >
                {formatRunLabel(run.strategy_name, run.strategy_version_number)}
              </button>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Succeeded Runs" subtitle="Recent finished runs available for comparison.">
        <div className="overflow-auto rounded-2xl border border-slate-800">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-950/60 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
              <tr>
                <th className="px-4 py-3">Pick</th>
                <th className="px-4 py-3">Run</th>
                <th className="px-4 py-3">Return</th>
                <th className="px-4 py-3">Sharpe</th>
                <th className="px-4 py-3">Max DD</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 bg-slate-950/40">
              {loadingRuns ? (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-slate-400">Loading succeeded runs…</td>
                </tr>
              ) : (
                availableRuns.map((run) => {
                  const checked = selectedRunIds.includes(run.run_id);
                  return (
                    <tr key={run.run_id} className="hover:bg-slate-800/50">
                      <td className="px-4 py-3">
                        <input type="checkbox" checked={checked} onChange={() => toggleRun(run.run_id)} className="h-4 w-4 rounded border-slate-700 bg-slate-950" />
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-white">{formatRunLabel(run.strategy_name, run.strategy_version_number)}</div>
                        <div className="mt-1 font-mono text-xs text-slate-500">{run.run_id}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-300">{formatPct(run.total_return_pct)}</td>
                      <td className="px-4 py-3 text-slate-300">{formatNumber(run.sharpe_ratio)}</td>
                      <td className="px-4 py-3 text-slate-300">{formatPct(run.max_drawdown_pct)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {comparison ? (
        <SectionCard title="Comparison Summary" subtitle="Metadata-only summary from GET /runs/compare.">
          <div className="overflow-auto rounded-2xl border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-950/60 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                <tr>
                  <th className="px-4 py-3">Run</th>
                  <th className="px-4 py-3">Total Return</th>
                  <th className="px-4 py-3">Alpha</th>
                  <th className="px-4 py-3">CAGR</th>
                  <th className="px-4 py-3">Sharpe</th>
                  <th className="px-4 py-3">Max DD</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-950/40">
                {comparison.runs.map((run) => (
                  <tr key={run.run_id} className="hover:bg-slate-800/50">
                    <td className="px-4 py-3 font-medium text-white">{formatRunLabel(run.strategy_name, run.strategy_version_number)}</td>
                    <td className="px-4 py-3 text-slate-300">{formatPct(run.total_return_pct)}</td>
                    <td className="px-4 py-3 text-slate-300">{formatPct(run.alpha_vs_benchmark_pct)}</td>
                    <td className="px-4 py-3 text-slate-300">{formatPct(run.cagr_pct)}</td>
                    <td className="px-4 py-3 text-slate-300">{formatNumber(run.sharpe_ratio)}</td>
                    <td className="px-4 py-3 text-slate-300">{formatPct(run.max_drawdown_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      ) : null}

      {comparisonChart ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <CurveChart title="Strategy Curves" subtitle="Normalized strategy equity curves from GET /runs/compare/chart." curves={comparisonChart.strategy_curves} />
          <CurveChart title="Benchmark Curves" subtitle="Normalized benchmark equity curves for the same runs." curves={comparisonChart.benchmark_curves} />
          <CurveChart title="Strategy Drawdowns" subtitle="Strategy drawdown overlays for selected runs." curves={comparisonChart.strategy_drawdown_curves} yFormatter={pctFormatter} zeroLine />
          <CurveChart title="Benchmark Drawdowns" subtitle="Benchmark drawdown overlays for selected runs." curves={comparisonChart.benchmark_drawdown_curves} yFormatter={pctFormatter} zeroLine />
        </div>
      ) : null}
    </div>
  );
}
