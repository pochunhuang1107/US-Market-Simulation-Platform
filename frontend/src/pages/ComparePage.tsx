import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';

import { ComparisonInsightSummary } from '../components/compare/ComparisonInsightSummary';
import { CurveChart, pctFormatter } from '../components/compare/CurveChart';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchRun, fetchRunComparison, fetchRunComparisonChart, fetchRunsDashboard } from '../lib/api';
import {
  formatNumber,
  formatPct,
  formatRunLabel,
  formatSavedSweepVariantSource,
  isSavedSweepVariantResult,
  shortRunId
} from '../lib/formatters';
import type { RunComparisonChartResponse, RunComparisonResponse, RunDashboardListItem, RunResponse } from '../types/api';

const MAX_COMPARE_RUNS = 4;

type ComparableRunMetric = RunComparisonResponse['runs'][number];
type ComparableRunListItem = RunDashboardListItem | ComparableRunMetric;

type ParsedRunIdsParam = {
  runIds: string[];
  exceedsLimit: boolean;
};

type CompareLocationState = {
  compareResetKey?: number;
} | null;

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
  const message = error instanceof Error ? error.message : 'Failed to compare results';
  if (message.toLowerCase().includes('comparison limit reached')) {
    return `Comparison limit reached for your plan. Select up to ${MAX_COMPARE_RUNS} results.`;
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
    const label = formatComparableRunLabel(run);
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

function formatComparableRunLabel(run: ComparableRunListItem): string {
  const baseLabel = formatRunLabel(run.strategy_name, run.strategy_version_number, run.run_id);
  return isSavedSweepVariantResult(run) ? `Saved sweep variant · ${baseLabel}` : baseLabel;
}

function runResponseToDashboardItem(run: RunResponse): RunDashboardListItem {
  const summary = run.summary_json ?? {};

  return {
    run_id: run.id,
    strategy_id: run.strategy_id,
    strategy_version_id: run.strategy_version_id,
    strategy_name: run.strategy_name,
    strategy_version_number: run.strategy_version_number,
    source: run.source,
    source_sweep_run_id: run.source_sweep_run_id,
    source_variant_id: run.source_variant_id,
    source_variant_rank: run.source_variant_rank,
    source_ranking_metric: run.source_ranking_metric,
    status: run.status,
    run_type: run.run_type,
    executor_type: run.executor_type,
    created_at: run.created_at,
    finished_at: run.finished_at,
    progress_pct: run.progress_pct,
    progress_message: run.progress_message,
    artifact_storage_type: run.artifact_storage_type,
    has_artifacts: Boolean(run.artifact_manifest_json),
    total_return_pct: typeof summary.total_return_pct === 'number' ? summary.total_return_pct : null,
    benchmark_return_pct: typeof summary.benchmark_return_pct === 'number' ? summary.benchmark_return_pct : null,
    alpha_vs_benchmark_pct: typeof summary.alpha_vs_benchmark_pct === 'number' ? summary.alpha_vs_benchmark_pct : null,
    cagr_pct: typeof summary.cagr_pct === 'number' ? summary.cagr_pct : null,
    sharpe_ratio: typeof summary.sharpe_ratio === 'number' ? summary.sharpe_ratio : null,
    max_drawdown_pct: typeof summary.max_drawdown_pct === 'number' ? summary.max_drawdown_pct : null,
    trade_count: typeof summary.trade_count === 'number' ? summary.trade_count : null,
    win_rate_pct: typeof summary.win_rate_pct === 'number' ? summary.win_rate_pct : null
  };
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
  const relabelBenchmarkCurves = (curves: RunComparisonChartResponse['benchmark_curves']) =>
    curves.map((curve) => {
      const runLabel = labelByRunId.get(curve.run_id) ?? curve.label;
      return {
        ...curve,
        label: curve.benchmark_label ? `${curve.benchmark_label} · ${runLabel}` : runLabel
      };
    });

  return {
    strategy_curves: relabelCurves(chart.strategy_curves),
    benchmark_curves: relabelBenchmarkCurves(chart.benchmark_curves),
    strategy_drawdown_curves: relabelCurves(chart.strategy_drawdown_curves),
    benchmark_drawdown_curves: relabelBenchmarkCurves(chart.benchmark_drawdown_curves),
    chart_window_mode: chart.chart_window_mode,
    chart_overlap_start: chart.chart_overlap_start,
    chart_overlap_end: chart.chart_overlap_end
  };
}

function getSharedBenchmarkNote(curves: RunComparisonChartResponse['benchmark_curves']): string | undefined {
  if (curves.length === 0) return undefined;

  const benchmarkLabels = curves.map((curve) => curve.benchmark_label).filter(Boolean);
  if (benchmarkLabels.length !== curves.length) return undefined;

  const uniqueLabels = new Set(benchmarkLabels);
  if (uniqueLabels.size !== 1) return undefined;

  return `Benchmark: ${benchmarkLabels[0]}`;
}

function formatDateOnly(value: string | null): string {
  if (!value) return 'Unavailable';
  return value;
}

function getComparisonChartSubtitle(
  chart: RunComparisonChartResponse,
  fullPeriodSubtitle: string
): string {
  if (chart.chart_window_mode === 'COMMON_OVERLAP' && chart.chart_overlap_start && chart.chart_overlap_end) {
    return `Normalized to the common overlap window: ${formatDateOnly(chart.chart_overlap_start)} to ${formatDateOnly(chart.chart_overlap_end)}.`;
  }

  return fullPeriodSubtitle;
}

function ComparisonDateWindowPanel({
  comparison,
  onCompareAnotherSet
}: {
  comparison: RunComparisonResponse;
  onCompareAnotherSet: () => void;
}) {
  const { metadata } = comparison;
  const hasNoCommonOverlap = metadata.has_common_overlap === false;
  if (!metadata.warning_message && !hasNoCommonOverlap) return null;

  const labelByRunId = buildComparisonLabelMap(comparison.runs);
  const hasOverlapWindow = metadata.has_common_overlap && metadata.overlap_start && metadata.overlap_end;
  const isMissingWindowWarning = metadata.warning_message?.toLowerCase().includes('could not be inferred') ?? false;
  const title = hasNoCommonOverlap
    ? 'These results do not have a common comparison window.'
    : isMissingWindowWarning
    ? 'Date ranges unavailable'
    : 'Date ranges differ';
  const toneClass = hasNoCommonOverlap && !isMissingWindowWarning ? 'app-alert-error' : 'app-alert-warning';

  return (
    <section className={`rounded-2xl border p-5 ${toneClass}`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <h2 className="text-base font-semibold app-title">{title}</h2>
          <p className="mt-2 text-sm leading-6">
            {hasNoCommonOverlap
              ? 'The selected results were tested over non-overlapping date ranges, so the app cannot determine a fair winner.'
              : hasOverlapWindow
              ? `Common overlap: ${formatDateOnly(metadata.overlap_start)} to ${formatDateOnly(metadata.overlap_end)}.`
              : metadata.warning_message}
          </p>
          {hasNoCommonOverlap ? null : (
            <p className="mt-2 text-sm leading-6">
              {metadata.warning_message}
            </p>
          )}
          {hasNoCommonOverlap ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onCompareAnotherSet}
                className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Compare another set
              </button>
              <Link
                to="/runs"
                className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Back to result history
              </Link>
            </div>
          ) : null}
        </div>
        <div className="min-w-full lg:min-w-80">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] app-label">
            Original result windows
          </div>
          <dl className="mt-3 grid gap-2 text-sm">
            {metadata.run_windows.map((window) => (
              <div
                key={window.run_id}
                className="flex flex-col gap-1 rounded-xl border border-current/20 bg-black/5 px-3 py-2 dark:bg-white/5 sm:flex-row sm:items-center sm:justify-between"
              >
                <dt className="font-medium app-title">{labelByRunId.get(window.run_id) ?? shortRunId(window.run_id)}</dt>
                <dd className="font-mono text-xs">
                  {formatDateOnly(window.start_date)} to {formatDateOnly(window.end_date)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
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
            Review the strongest candidates, pick another group, or return to the result history.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {bestReturnRun ? (
            <Link
              to={`/runs/${bestReturnRun.run_id}`}
              className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition"
            >
              Open best return result
            </Link>
          ) : null}
          {bestSharpeRun ? (
            <Link
              to={`/runs/${bestSharpeRun.run_id}`}
              className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
            >
              Open best Sharpe result
            </Link>
          ) : null}
          <Link
            to="/runs"
            className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
          >
            Back to result history
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

const ComparisonResults = memo(function ComparisonResults({
  comparison,
  onCompareAnotherSet
}: {
  comparison: RunComparisonResponse;
  onCompareAnotherSet: () => void;
}) {
  const hasNoCommonOverlap = comparison.metadata.has_common_overlap === false;
  const usesOverlapMetrics =
    comparison.metadata.window_mode === 'COMMON_OVERLAP_METRICS' &&
    comparison.metadata.overlap_start &&
    comparison.metadata.overlap_end;

  return (
    <>
      <ComparisonDateWindowPanel comparison={comparison} onCompareAnotherSet={onCompareAnotherSet} />
      {!hasNoCommonOverlap ? <ComparisonInsightSummary comparison={comparison} /> : null}
      {!hasNoCommonOverlap ? (
        <NextComparisonSteps comparison={comparison} onCompareAnotherSet={onCompareAnotherSet} />
      ) : null}

      <SectionCard
        title={hasNoCommonOverlap ? 'Full-period Reference Summary' : 'Comparison Summary'}
        subtitle={
          hasNoCommonOverlap
            ? 'Full-period metrics for the selected results. These rows are reference only and should not be read as a fair winner comparison.'
            : usesOverlapMetrics
            ? `Metrics are calculated over the common overlap window: ${formatDateOnly(comparison.metadata.overlap_start)} to ${formatDateOnly(comparison.metadata.overlap_end)}.`
            : 'Metric summary for the selected results.'
        }
      >
        <div className="app-table overflow-auto rounded-2xl border">
          <table className="min-w-full divide-y app-divider text-sm">
            <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
              <tr>
                <th className="px-4 py-3">Result</th>
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
                    <div>{formatComparableRunLabel(run)}</div>
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
    </>
  );
});

const ComparisonCharts = memo(function ComparisonCharts({ chart }: { chart: RunComparisonChartResponse }) {
  const strategySubtitle = useMemo(
    () => getComparisonChartSubtitle(chart, 'How each selected strategy result grew over the comparison window.'),
    [chart]
  );
  const benchmarkSubtitle = useMemo(
    () => getComparisonChartSubtitle(chart, "How each result's benchmark performed over the same window."),
    [chart]
  );
  const strategyDrawdownSubtitle = useMemo(
    () => getComparisonChartSubtitle(chart, 'How far each strategy fell from its previous high.'),
    [chart]
  );
  const benchmarkDrawdownSubtitle = useMemo(
    () => getComparisonChartSubtitle(chart, 'How far each benchmark fell from its previous high.'),
    [chart]
  );
  const sharedBenchmarkNote = useMemo(() => getSharedBenchmarkNote(chart.benchmark_curves), [chart.benchmark_curves]);
  const sharedDrawdownBenchmarkNote = useMemo(
    () => getSharedBenchmarkNote(chart.benchmark_drawdown_curves),
    [chart.benchmark_drawdown_curves]
  );

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <CurveChart
        title="Strategy Performance"
        subtitle={strategySubtitle}
        curves={chart.strategy_curves}
      />
      <CurveChart
        title="Benchmark / Buy-and-Hold Reference"
        subtitle={benchmarkSubtitle}
        note={sharedBenchmarkNote}
        curves={chart.benchmark_curves}
      />
      <CurveChart
        title="Strategy Drawdowns"
        subtitle={strategyDrawdownSubtitle}
        curves={chart.strategy_drawdown_curves}
        yFormatter={pctFormatter}
        zeroLine
      />
      <CurveChart
        title="Benchmark Drawdowns"
        subtitle={benchmarkDrawdownSubtitle}
        note={sharedDrawdownBenchmarkNote}
        curves={chart.benchmark_drawdown_curves}
        yFormatter={pctFormatter}
        zeroLine
      />
    </div>
  );
});

export function ComparePage() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdsParam = searchParams.get('runIds');
  const compareResetKey = (location.state as CompareLocationState)?.compareResetKey;
  const parsedRunIdsParam = useMemo(() => parseRunIdsParam(runIdsParam), [runIdsParam]);
  const initialSelectedRunIds = parsedRunIdsParam.runIds;
  const urlRunIdLimitExceeded = parsedRunIdsParam.exceedsLimit;
  const autoCompareKeyRef = useRef<string | null>(null);
  const compareRequestIdRef = useRef(0);

  const [availableRuns, setAvailableRuns] = useState<RunDashboardListItem[]>([]);
  const [hydratedSelectedRuns, setHydratedSelectedRuns] = useState<Record<string, RunDashboardListItem>>({});
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>(initialSelectedRunIds);
  const [comparison, setComparison] = useState<RunComparisonResponse | null>(null);
  const [comparisonChart, setComparisonChart] = useState<RunComparisonChartResponse | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!runIdsParam) {
      autoCompareKeyRef.current = null;
      compareRequestIdRef.current += 1;
      setSelectedRunIds([]);
      setHydratedSelectedRuns({});
      setComparison(null);
      setComparisonChart(null);
      setErrorMessage(null);
      setLoadingComparison(false);
      return;
    }

    if (urlRunIdLimitExceeded) {
      autoCompareKeyRef.current = null;
      compareRequestIdRef.current += 1;
      setSelectedRunIds([]);
      setHydratedSelectedRuns({});
      setComparison(null);
      setComparisonChart(null);
      setErrorMessage(`Comparison limit reached for your plan. Select up to ${MAX_COMPARE_RUNS} results.`);
      setLoadingComparison(false);
      return;
    }

    setSelectedRunIds(initialSelectedRunIds);
  }, [initialSelectedRunIds, runIdsParam, urlRunIdLimitExceeded]);

  useEffect(() => {
    if (!compareResetKey) return;
    clearComparisonWorkspace();
  }, [compareResetKey]);

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
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load comparable results');
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

  useEffect(() => {
    let ignore = false;
    const availableIds = new Set(availableRuns.map((run) => run.run_id));
    const missingRunIds = selectedRunIds.filter(
      (runId) => !availableIds.has(runId) && !hydratedSelectedRuns[runId]
    );

    if (missingRunIds.length === 0) return;

    async function hydrateSelectedRuns() {
      try {
        const hydrated = await Promise.all(
          missingRunIds.map(async (runId) => runResponseToDashboardItem(await fetchRun(runId)))
        );
        if (ignore) return;

        setHydratedSelectedRuns((current) => {
          const next = { ...current };
          hydrated.forEach((run) => {
            next[run.run_id] = run;
          });
          return next;
        });
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load selected result');
        }
      }
    }

    void hydrateSelectedRuns();
    return () => {
      ignore = true;
    };
  }, [availableRuns, hydratedSelectedRuns, selectedRunIds]);

  const selectedRuns = useMemo(() => {
    const availableById = new Map(availableRuns.map((run) => [run.run_id, run]));

    return selectedRunIds
      .map((runId) => availableById.get(runId) ?? hydratedSelectedRuns[runId] ?? null)
      .filter((run): run is RunDashboardListItem => run !== null);
  }, [availableRuns, hydratedSelectedRuns, selectedRunIds]);

  const selectionLimitReached = selectedRunIds.length >= MAX_COMPARE_RUNS;
  const selectedRunsSubtitle =
    selectedRunIds.length === 1
      ? 'Choose one more result to compare.'
      : selectionLimitReached
        ? 'Comparison limit reached. Remove one selected result before adding another.'
        : 'Choose at least two succeeded results to compare.';
  const shouldShowComparisonCharts = Boolean(
    comparisonChart && comparison?.metadata.has_common_overlap !== false
  );

  async function handleCompare(runIdsOverride?: string[]) {
    const runIds = runIdsOverride ?? selectedRunIds;

    if (runIds.length < 2) {
      setErrorMessage('Select at least two succeeded results to compare.');
      return;
    }

    const requestId = ++compareRequestIdRef.current;
    setLoadingComparison(true);
    setErrorMessage(null);
    setComparison(null);
    setComparisonChart(null);

    try {
      const [summary, chart] = await Promise.all([
        fetchRunComparison(runIds),
        fetchRunComparisonChart(runIds)
      ]);
      if (requestId !== compareRequestIdRef.current) return;
      const labelByRunId = buildComparisonLabelMap(summary.runs);
      setComparison(summary);
      setComparisonChart(relabelComparisonChart(chart, labelByRunId));
    } catch (error) {
      if (requestId !== compareRequestIdRef.current) return;
      setErrorMessage(formatCompareError(error));
      setComparison(null);
      setComparisonChart(null);
    } finally {
      if (requestId === compareRequestIdRef.current) {
        setLoadingComparison(false);
      }
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

  function clearComparisonWorkspace() {
    autoCompareKeyRef.current = null;
    compareRequestIdRef.current += 1;
    setSelectedRunIds([]);
    setHydratedSelectedRuns({});
    setComparison(null);
    setComparisonChart(null);
    setErrorMessage(null);
    setLoadingComparison(false);
  }

  const resetComparison = useCallback(function resetComparison() {
    setSearchParams({});
    clearComparisonWorkspace();
  }, [setSearchParams]);

  const toggleRun = useCallback(function toggleRun(runId: string) {
    setSelectedRunIds((current) => {
      if (current.includes(runId)) {
        return current.filter((value) => value !== runId);
      }

      if (current.length >= MAX_COMPARE_RUNS) {
        return current;
      }

      return [...current, runId];
    });
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Compare"
        title="Result Comparison Workspace"
        description="Select multiple succeeded results, then compare normalized strategy curves, benchmark curves, and drawdown series."
        actions={
          <button
            type="button"
            onClick={() => {
              void handleCompare();
            }}
            disabled={loadingComparison || selectedRunIds.length < 2}
            className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loadingComparison ? 'Comparing…' : 'Compare selected results'}
          </button>
        }
      />

      {errorMessage ? <StateCard title="Comparison issue" description={errorMessage} tone="error" /> : null}

      {loadingComparison ? (
        <StateCard
          title="Comparing selected results"
          description="Loading comparison metrics and chart overlays. This may take a few seconds for larger run artifacts."
        />
      ) : null}

      {comparison ? <ComparisonResults comparison={comparison} onCompareAnotherSet={resetComparison} /> : null}

      {shouldShowComparisonCharts && comparisonChart ? <ComparisonCharts chart={comparisonChart} /> : null}

      <SectionCard
        title={`Selected Results (${selectedRunIds.length} / ${MAX_COMPARE_RUNS})`}
        subtitle={selectedRunsSubtitle}
      >
        {selectedRunIds.length > 0 && selectedRuns.length === 0 ? (
          <p className="text-sm app-text-muted">Loading selected result…</p>
        ) : selectedRuns.length === 0 ? (
          <p className="text-sm app-text-muted">No results selected yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {selectedRuns.map((run) => {
              const label = formatComparableRunLabel(run);
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
        title="Comparable Results"
        subtitle={`Recent finished results available for comparison. Select up to ${MAX_COMPARE_RUNS} results.`}
      >
        <div className="app-table overflow-auto rounded-2xl border">
          <table className="min-w-full divide-y app-divider text-sm">
            <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
              <tr>
                <th className="px-4 py-3">Pick</th>
                <th className="px-4 py-3">Result</th>
                <th className="px-4 py-3">Return</th>
                <th className="px-4 py-3">Sharpe</th>
                <th className="px-4 py-3">Max DD</th>
              </tr>
            </thead>
            <tbody className="divide-y app-divider">
              {loadingRuns ? (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center app-text-muted">
                    Loading comparable results…
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
                          {formatComparableRunLabel(run)}
                        </div>
                        <div className="mt-1 text-xs app-text-soft">
                          {isSavedSweepVariantResult(run) ? formatSavedSweepVariantSource(run) : run.run_id}
                        </div>
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
