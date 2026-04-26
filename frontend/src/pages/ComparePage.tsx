import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { ComparisonInsightSummary } from '../components/compare/ComparisonInsightSummary';
import { CurveChart, pctFormatter } from '../components/compare/CurveChart';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchRunComparison, fetchRunComparisonChart, fetchRunsDashboard } from '../lib/api';
import { formatNumber, formatPct, formatRunLabel, shortRunId } from '../lib/formatters';
import type { RunComparisonChartResponse, RunComparisonResponse, RunDashboardListItem } from '../types/api';

const MAX_COMPARE_RUNS = 4;

type ComparableRunMetric = RunComparisonResponse['runs'][number];

type ParsedRunIdsParam = {
  runIds: string[];
  exceedsLimit: boolean;
};

function parseRunIdsParam(value: string | null): ParsedRunIdsParam {
  if (!value) return { runIds: [], exceedsLimit: false };

  const runIds = Array.from(
    new Set(
      value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );

  return {
    runIds: runIds.length > MAX_COMPARE_RUNS ? [] : runIds,
    exceedsLimit: runIds.length > MAX_COMPARE_RUNS
  };
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function formatCompareError(error: unknown): string {
  const message = error instanceof Error ? error.message : 'Failed to compare runs';
  if (message.toLowerCase().includes('comparison limit reached')) {
    return `Comparison limit reached for your plan. Select up to ${MAX_COMPARE_RUNS} runs.`;
  }
  return message;
}

function pickBestRun(
  runs: ComparableRunMetric[],
  selector: (run: ComparableRunMetric) => number | null
) {
  const candidates = runs
    .map((run) => ({ run, value: selector(run) }))
    .filter((item): item is { run: ComparableRunMetric; value: number } => isFiniteNumber(item.value));

  if (candidates.length === 0) return null;

  return candidates.sort((a, b) => b.value - a.value)[0].run;
}

function buildComparisonLabelMap(runs: ComparableRunMetric[]) {
  const baseLabels = new Map<string, string>();
  const labelCounts = new Map<string, number>();

  runs.forEach((run) => {
    const label = formatRunLabel(run.strategy_name, run.strategy_version_number, run.run_id);
    baseLabels.set(run.run_id, label);
    labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1);
  });

  return new Map(
    runs.map((run) => {
      const label = baseLabels.get(run.run_id) ?? shortRunId(run.run_id);
      const uniqueLabel =
        (labelCounts.get(label) ?? 0) > 1 ? `${label} · ${shortRunId(run.run_id)}` : label;
      return [run.run_id, uniqueLabel];
    })
  );
}

function relabelComparisonChart(
  chart: RunComparisonChartResponse,
  labelByRunId: Map<string, string>
): RunComparisonChartResponse {
  const relabelCurves = (curves: RunComparisonChartResponse['strategy_curves']) =>
    curves.map((curve) => ({
      ...curve,
      label: labelByRunId.get(curve.run_id) ?? curve.label
    }));

  return {
    strategy_curves: relabelCurves(chart.strategy_curves),
    benchmark_curves: relabelCurves(chart.benchmark_curves),
    strategy_drawdown_curves: relabelCurves(chart.strategy_drawdown_curves),
    benchmark_drawdown_curves: relabelCurves(chart.benchmark_drawdown_curves)
  };
}

function NextComparisonSteps({
  comparison,
  onCompareAnotherSet
}: {
  comparison: RunComparisonResponse;
  onCompareAnotherSet: () => void;
}) {
  const bestReturnRun = pickBestRun(comparison.runs, (run) => run.total_return_pct);
  const bestSharpeRun = pickBestRun(comparison.runs, (run) => run.sharpe_ratio);

  return (
    <section className="app-card app-shadow-soft rounded-3xl border p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
            Next comparison steps
          </div>
          <p className="app-text-muted mt-2 text-sm leading-6">
            Review the strongest candidates, pick another group, or return to the run history.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {bestReturnRun ? (
            <Link
              to={`/runs/${bestReturnRun.run_id}`}
              className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition"
            >
              Open best return run
            </Link>
          ) : null}
          {bestSharpeRun ? (
            <Link
              to={`/runs/${bestSharpeRun.run_id}`}
              className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
            >
              Open best Sharpe run
            </Link>
          ) : null}
          <Link
            to="/runs"
            className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
          >
            Back to run history
          </Link>
          <button
            type="button"
            onClick={onCompareAnotherSet}
            className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
          >
            Compare another set
          </button>
        </div>
      </div>
    </section>
  );
}

export function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdsParam = searchParams.get('runIds');
  const parsedRunIdsParam = useMemo(() => parseRunIdsParam(runIdsParam), [runIdsParam]);
  const initialSelectedRunIds = parsedRunIdsParam.runIds;
  const urlRunIdLimitExceeded = parsedRunIdsParam.exceedsLimit;
  const autoCompareKeyRef = useRef<string | null>(null);

  const [availableRuns, setAvailableRuns] = useState<RunDashboardListItem[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>(initialSelectedRunIds);
  const [comparison, setComparison] = useState<RunComparisonResponse | null>(null);
  const [comparisonChart, setComparisonChart] = useState<RunComparisonChartResponse | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (urlRunIdLimitExceeded) {
      autoCompareKeyRef.current = null;
      setSelectedRunIds([]);
      setComparison(null);
      setComparisonChart(null);
      setErrorMessage(`Comparison limit reached for your plan. Select up to ${MAX_COMPARE_RUNS} runs.`);
      setLoadingComparison(false);
      return;
    }

    if (initialSelectedRunIds.length >= 2) {
      setSelectedRunIds(initialSelectedRunIds);
    }
  }, [initialSelectedRunIds, urlRunIdLimitExceeded]);

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

  const selectionLimitReached = selectedRunIds.length >= MAX_COMPARE_RUNS;

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
      const labelByRunId = buildComparisonLabelMap(summary.runs);
      setComparison(summary);
      setComparisonChart(relabelComparisonChart(chart, labelByRunId));
    } catch (error) {
      setErrorMessage(formatCompareError(error));
      setComparison(null);
      setComparisonChart(null);
    } finally {
      setLoadingComparison(false);
    }
  }

  useEffect(() => {
    if (urlRunIdLimitExceeded) return;
    if (initialSelectedRunIds.length < 2) return;

    const compareKey = initialSelectedRunIds.join(',');
    if (autoCompareKeyRef.current === compareKey) return;

    autoCompareKeyRef.current = compareKey;
    void handleCompare(initialSelectedRunIds);
  }, [initialSelectedRunIds, urlRunIdLimitExceeded]);

  function resetComparison() {
    autoCompareKeyRef.current = null;
    setSearchParams({});
    setSelectedRunIds([]);
    setComparison(null);
    setComparisonChart(null);
    setErrorMessage(null);
    setLoadingComparison(false);
  }

  function toggleRun(runId: string) {
    setSelectedRunIds((current) => {
      if (current.includes(runId)) {
        return current.filter((value) => value !== runId);
      }

      if (current.length >= MAX_COMPARE_RUNS) {
        return current;
      }

      return [...current, runId];
    });
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

      {loadingComparison ? (
        <StateCard
          title="Comparing selected runs"
          description="Loading comparison metrics and chart overlays. This may take a few seconds for larger run artifacts."
        />
      ) : null}

      {comparison ? <ComparisonInsightSummary comparison={comparison} /> : null}
      {comparison ? (
        <NextComparisonSteps comparison={comparison} onCompareAnotherSet={resetComparison} />
      ) : null}

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
                      <div>{formatRunLabel(run.strategy_name, run.strategy_version_number, run.run_id)}</div>
                      <div className="mt-1 font-mono text-xs font-normal app-text-soft">
                        {shortRunId(run.run_id)}
                      </div>
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

      <SectionCard
        title={`Selected Runs (${selectedRunIds.length} / ${MAX_COMPARE_RUNS})`}
        subtitle={
          selectionLimitReached
            ? 'Comparison limit reached. Remove one selected run before adding another.'
            : 'Choose at least two succeeded runs to compare.'
        }
      >
        {selectedRuns.length === 0 ? (
          <p className="text-sm app-text-muted">No runs selected yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {selectedRuns.map((run) => {
              const label = formatRunLabel(run.strategy_name, run.strategy_version_number, run.run_id);
              const idLabel = shortRunId(run.run_id);
              return (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => toggleRun(run.run_id)}
                  className="app-badge rounded-full px-3 py-1.5 text-xs font-medium"
                >
                  <span>{label}</span>
                  {label.includes(idLabel) ? null : (
                    <span className="ml-1 font-mono app-text-soft">{idLabel}</span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Succeeded Runs"
        subtitle={`Recent finished runs available for comparison. Select up to ${MAX_COMPARE_RUNS} runs.`}
      >
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
                          disabled={!checked && selectionLimitReached}
                          onChange={() => toggleRun(run.run_id)}
                          className="app-checkbox h-4 w-4 rounded disabled:cursor-not-allowed disabled:opacity-40"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium app-title">
                          {formatRunLabel(run.strategy_name, run.strategy_version_number, run.run_id)}
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
