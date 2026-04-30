import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';

import { ComparisonInsightSummary } from '../components/compare/ComparisonInsightSummary';
import { CurveChart, pctFormatter } from '../components/compare/CurveChart';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchRun, fetchRunComparison, fetchRunComparisonChart, fetchRunsDashboard, fetchSweepVariantDetail } from '../lib/api';
import {
  formatNumber,
  formatPct,
  formatRunLabel,
  formatSavedSweepVariantSource,
  isSavedSweepVariantResult,
  shortRunId
} from '../lib/formatters';
import { formatParameterSummary, isRecord, toNumber, toStringValue } from '../lib/sweepVariants';
import type { RunComparisonChartResponse, RunComparisonResponse, RunDashboardListItem, RunResponse, SweepComparableVariantItem } from '../types/api';

const MAX_COMPARE_RUNS = 4;

type ComparableRunMetric = RunComparisonResponse['runs'][number];
type ComparableRunListItem = RunDashboardListItem | ComparableRunMetric | SweepComparableVariantItem;
type SelectedComparableResult = RunDashboardListItem | SweepComparableVariantItem;

type ParsedRunIdsParam = {
  runIds: string[];
  exceedsLimit: boolean;
};

type ParsedResultsParam = {
  resultRefs: string[];
  exceedsLimit: boolean;
};

type CompareLocationState = {
  compareResetKey?: number;
} | null;

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
    >
      {expanded ? <path d="m6 8 4 4 4-4" /> : <path d="m8 6 4 4-4 4" />}
    </svg>
  );
}

function runResultRef(runId: string): string {
  return `run:${runId}`;
}

function sweepVariantResultRef(sweepRunId: string, variantId: string): string {
  return `sweep_variant:${sweepRunId}:${variantId}`;
}

function parseSweepVariantRef(value: string): { sweepRunId: string; variantId: string } | null {
  const parts = value.split(':');
  if (parts.length !== 3 || parts[0] !== 'sweep_variant' || !parts[1] || !parts[2]) return null;
  return { sweepRunId: parts[1], variantId: parts[2] };
}

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

function parseResultsParam(value: string | null): ParsedResultsParam {
  if (!value) return { resultRefs: [], exceedsLimit: false };

  const resultRefs = Array.from(
    new Set(
      value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );

  return {
    resultRefs: resultRefs.length > MAX_COMPARE_RUNS ? [] : resultRefs,
    exceedsLimit: resultRefs.length > MAX_COMPARE_RUNS
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
    baseLabels.set(comparableResultRef(run), label);
    labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1);
  });

  return new Map(
    runs.map((run) => {
      const ref = comparableResultRef(run);
      const label = baseLabels.get(ref) ?? shortComparableRef(ref);
      const uniqueLabel =
        (labelCounts.get(label) ?? 0) > 1 ? `${label} · ${shortComparableRef(ref)}` : label;
      return [ref, uniqueLabel];
    })
  );
}

function formatComparableRunLabel(run: ComparableRunListItem): string {
  if ('label' in run && run.label && ('result_type' in run || 'sweep_run_id' in run)) {
    return run.label;
  }
  if ('sweep_run_id' in run) {
    return run.label;
  }
  const baseLabel = formatRunLabel(run.strategy_name, run.strategy_version_number, run.run_id);
  return isSavedSweepVariantResult(run) ? `Saved sweep variant · ${baseLabel}` : baseLabel;
}

function comparableResultRef(result: ComparableRunListItem): string {
  if ('comparable_result_ref' in result && result.comparable_result_ref) return result.comparable_result_ref;
  if ('result_ref' in result && result.result_ref) return result.result_ref;
  if ('sweep_run_id' in result) return sweepVariantResultRef(result.sweep_run_id, result.variant_id);
  return runResultRef(result.run_id);
}

function shortComparableRef(ref: string): string {
  const parsed = parseSweepVariantRef(ref);
  if (parsed) return `${shortRunId(parsed.sweepRunId)}:${shortRunId(parsed.variantId)}`;
  return shortRunId(ref.replace(/^run:/, ''));
}

function isParameterSweepGroup(run: RunDashboardListItem): boolean {
  return run.run_type === 'PARAMETER_SWEEP' || run.result_type === 'PARAMETER_SWEEP_GROUP';
}

function formatSweepVariantSelectionLabel(run: RunDashboardListItem, variant: Record<string, unknown>, rank: number | null): string {
  const rankLabel = rank ? `Rank #${rank}` : 'Variant';
  return `${formatComparableRunLabel(run)} · ${rankLabel} · ${formatParameterSummary(variant.parameters)}`;
}

function runResponseLabel(run: RunResponse): string {
  const draftConfig = isRecord(run.request_payload?.draft_config) ? run.request_payload.draft_config : null;
  const baseConfig = isRecord(run.request_payload?.base_config) ? run.request_payload.base_config : null;
  const configName = toStringValue(draftConfig?.name) ?? toStringValue(baseConfig?.name);
  if (configName) return configName;
  return formatRunLabel(run.strategy_name, run.strategy_version_number, run.id);
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
    comparable_result_ref: runResultRef(run.id),
    result_type: run.run_type === 'PARAMETER_SWEEP' ? 'PARAMETER_SWEEP_GROUP' : 'RUN',
    label: runResponseLabel(run),
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
    win_rate_pct: typeof summary.win_rate_pct === 'number' ? summary.win_rate_pct : null,
    sweep_variant_count: null,
    sweep_variants: []
  };
}

function relabelComparisonChart(
  chart: RunComparisonChartResponse,
  labelByRunId: Map<string, string>
): RunComparisonChartResponse {
  const relabelCurves = (curves: RunComparisonChartResponse['strategy_curves']) =>
    curves.map((curve) => ({
      ...curve,
      label: labelByRunId.get(curve.result_ref ?? curve.run_id) ?? curve.label
    }));
  const relabelBenchmarkCurves = (curves: RunComparisonChartResponse['benchmark_curves']) =>
    curves.map((curve) => {
      const runLabel = labelByRunId.get(curve.result_ref ?? curve.run_id) ?? curve.label;
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
                <dt className="font-medium app-title">
                  {labelByRunId.get(window.result_ref ?? window.run_id) ?? shortComparableRef(window.result_ref ?? window.run_id)}
                </dt>
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
  const bestReturnUrl = bestReturnRun?.result_type === 'SWEEP_VARIANT' ? null : bestReturnRun ? `/runs/${bestReturnRun.run_id}` : null;
  const bestSharpeUrl = bestSharpeRun?.result_type === 'SWEEP_VARIANT' ? null : bestSharpeRun ? `/runs/${bestSharpeRun.run_id}` : null;

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
          {bestReturnUrl ? (
            <Link
              to={bestReturnUrl}
              className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition"
            >
              Open best return result
            </Link>
          ) : null}
          {bestSharpeUrl ? (
            <Link
              to={bestSharpeUrl}
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
                <tr key={run.result_ref ?? run.run_id} className="app-row-hover">
                  <td className="px-4 py-3 font-medium app-title">
                    <div>{formatComparableRunLabel(run)}</div>
                    <div className="mt-1 font-mono text-xs font-normal app-text-soft">
                      {shortComparableRef(run.result_ref ?? run.run_id)}
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
  const resultsParam = searchParams.get('results');
  const compareResetKey = (location.state as CompareLocationState)?.compareResetKey;
  const parsedRunIdsParam = useMemo(() => parseRunIdsParam(runIdsParam), [runIdsParam]);
  const parsedResultsParam = useMemo(() => parseResultsParam(resultsParam), [resultsParam]);
  const initialSelectedResultRefs = useMemo(
    () => (resultsParam ? parsedResultsParam.resultRefs : parsedRunIdsParam.runIds.map(runResultRef)),
    [parsedResultsParam.resultRefs, parsedRunIdsParam.runIds, resultsParam]
  );
  const urlSelectionLimitExceeded = resultsParam ? parsedResultsParam.exceedsLimit : parsedRunIdsParam.exceedsLimit;
  const compareRequestIdRef = useRef(0);

  const [availableRuns, setAvailableRuns] = useState<RunDashboardListItem[]>([]);
  const [expandedSweepRunIds, setExpandedSweepRunIds] = useState<Set<string>>(new Set());
  const [hydratedSelectedResults, setHydratedSelectedResults] = useState<Record<string, SelectedComparableResult>>({});
  const [selectedResultRefs, setSelectedResultRefs] = useState<string[]>(initialSelectedResultRefs);
  const [comparison, setComparison] = useState<RunComparisonResponse | null>(null);
  const [comparisonChart, setComparisonChart] = useState<RunComparisonChartResponse | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!runIdsParam && !resultsParam) {
      setSelectedResultRefs([]);
      setHydratedSelectedResults({});
      clearComparisonOutput();
      return;
    }

    if (urlSelectionLimitExceeded) {
      setSelectedResultRefs([]);
      setHydratedSelectedResults({});
      setComparison(null);
      setComparisonChart(null);
      setErrorMessage(`Comparison limit reached for your plan. Select up to ${MAX_COMPARE_RUNS} results.`);
      setLoadingComparison(false);
      return;
    }

    setSelectedResultRefs(initialSelectedResultRefs);
    clearComparisonOutput();
  }, [initialSelectedResultRefs, resultsParam, runIdsParam, urlSelectionLimitExceeded]);

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
    const availableByRef = new Map<string, SelectedComparableResult>();
    availableRuns.forEach((run) => {
      if (!isParameterSweepGroup(run)) {
        availableByRef.set(comparableResultRef(run), run);
      }
      run.sweep_variants.forEach((variant) => {
        availableByRef.set(variant.comparable_result_ref, variant);
      });
    });
    const missingResultRefs = selectedResultRefs.filter(
      (resultRef) => !availableByRef.has(resultRef) && !hydratedSelectedResults[resultRef]
    );

    if (missingResultRefs.length === 0) return;

    async function hydrateSelectedResults() {
      try {
        const hydrated = await Promise.all(
          missingResultRefs.map(async (resultRef) => {
            const parsedSweepVariant = parseSweepVariantRef(resultRef);
            if (parsedSweepVariant) {
              const detail = await fetchSweepVariantDetail(parsedSweepVariant.sweepRunId, parsedSweepVariant.variantId);
              const run = runResponseToDashboardItem(detail.run);
              const variant = detail.variant;
              return {
                comparable_result_ref: resultRef,
                sweep_run_id: parsedSweepVariant.sweepRunId,
                variant_id: parsedSweepVariant.variantId,
                label: formatSweepVariantSelectionLabel(run, variant, detail.rank || null),
                rank: detail.rank || null,
                parameters: isRecord(variant.parameters) ? variant.parameters : null,
                total_return_pct: toNumber(variant.total_return_pct),
                benchmark_return_pct: toNumber(variant.benchmark_return_pct),
                alpha_vs_benchmark_pct: toNumber(variant.alpha_vs_benchmark_pct),
                cagr_pct: toNumber(variant.cagr_pct),
                sharpe_ratio: toNumber(variant.sharpe_ratio),
                max_drawdown_pct: toNumber(variant.max_drawdown_pct),
                trade_count: toNumber(variant.trade_count),
                status: toStringValue(variant.status)
              } satisfies SweepComparableVariantItem;
            }

            const runId = resultRef.replace(/^run:/, '');
            return runResponseToDashboardItem(await fetchRun(runId));
          })
        );
        if (ignore) return;

        setHydratedSelectedResults((current) => {
          const next = { ...current };
          hydrated.forEach((result) => {
            next[comparableResultRef(result)] = result;
          });
          return next;
        });
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load selected result');
        }
      }
    }

    void hydrateSelectedResults();
    return () => {
      ignore = true;
    };
  }, [availableRuns, hydratedSelectedResults, selectedResultRefs]);

  const selectedResults = useMemo(() => {
    const availableByRef = new Map<string, SelectedComparableResult>();
    availableRuns.forEach((run) => {
      if (!isParameterSweepGroup(run)) {
        availableByRef.set(comparableResultRef(run), run);
      }
      run.sweep_variants.forEach((variant) => {
        availableByRef.set(variant.comparable_result_ref, variant);
      });
    });

    return selectedResultRefs
      .map((resultRef) => availableByRef.get(resultRef) ?? hydratedSelectedResults[resultRef] ?? null)
      .filter((result): result is SelectedComparableResult => result !== null);
  }, [availableRuns, hydratedSelectedResults, selectedResultRefs]);

  const selectionLimitReached = selectedResultRefs.length >= MAX_COMPARE_RUNS;
  const selectedRunsSubtitle =
    selectedResultRefs.length === 1
      ? 'Choose one more result to compare.'
      : selectionLimitReached
        ? 'Comparison limit reached. Remove one selected result before adding another.'
        : 'Choose at least two succeeded results to compare.';
  const shouldShowComparisonCharts = Boolean(
    comparisonChart && comparison?.metadata.has_common_overlap !== false
  );

  async function handleCompare(resultRefsOverride?: string[]) {
    const resultRefs = resultRefsOverride ?? selectedResultRefs;

    if (resultRefs.length < 2) {
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
        fetchRunComparison(resultRefs),
        fetchRunComparisonChart(resultRefs)
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

  function clearComparisonOutput() {
    compareRequestIdRef.current += 1;
    setComparison(null);
    setComparisonChart(null);
    setErrorMessage(null);
    setLoadingComparison(false);
  }

  function clearComparisonWorkspace() {
    setSelectedResultRefs([]);
    setHydratedSelectedResults({});
    clearComparisonOutput();
  }

  const resetComparison = useCallback(function resetComparison() {
    setSearchParams({});
    clearComparisonWorkspace();
  }, [setSearchParams]);

  const toggleResult = useCallback(function toggleResult(resultRef: string) {
    let next: string[];
    if (selectedResultRefs.includes(resultRef)) {
      next = selectedResultRefs.filter((value) => value !== resultRef);
    } else if (selectedResultRefs.length >= MAX_COMPARE_RUNS) {
      return;
    } else {
      next = [...selectedResultRefs, resultRef];
    }

    setSelectedResultRefs(next);
    clearComparisonOutput();
    const params = new URLSearchParams(searchParams);
    params.delete('runIds');
    if (next.length > 0) {
      params.set('results', next.join(','));
    } else {
      params.delete('results');
    }
    setSearchParams(params, { replace: true });
  }, [searchParams, selectedResultRefs, setSearchParams]);

  const toggleSweepExpanded = useCallback(function toggleSweepExpanded(runId: string) {
    setExpandedSweepRunIds((current) => {
      const next = new Set(current);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
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
            disabled={loadingComparison || selectedResultRefs.length < 2}
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
          description="Loading comparison metrics and chart overlays. This may take a few seconds for larger result artifacts."
        />
      ) : null}

      {comparison ? <ComparisonResults comparison={comparison} onCompareAnotherSet={resetComparison} /> : null}

      {shouldShowComparisonCharts && comparisonChart ? <ComparisonCharts chart={comparisonChart} /> : null}

      <SectionCard
        title={`Selected Results (${selectedResultRefs.length} / ${MAX_COMPARE_RUNS})`}
        subtitle={selectedRunsSubtitle}
      >
        {selectedResultRefs.length > 0 && selectedResults.length === 0 ? (
          <p className="text-sm app-text-muted">Loading selected result…</p>
        ) : selectedResults.length === 0 ? (
          <p className="text-sm app-text-muted">No results selected yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {selectedResults.map((run) => {
              const ref = comparableResultRef(run);
              const label = formatComparableRunLabel(run);
              const idLabel = shortComparableRef(ref);
              return (
                <button
                  key={ref}
                  type="button"
                  onClick={() => toggleResult(ref)}
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
                <th className="w-16 px-4 py-3">Pick</th>
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
                  const isSweepGroup = isParameterSweepGroup(run);
                  const resultRef = comparableResultRef(run);
                  const checked = selectedResultRefs.includes(resultRef);
                  const isExpanded = expandedSweepRunIds.has(run.run_id);
                  const variantCount = run.sweep_variant_count ?? run.sweep_variants.length;
                  return (
                    <Fragment key={run.run_id}>
                      <tr className={isSweepGroup ? 'app-surface-soft border-y app-divider' : 'app-row-hover'}>
                        <td className="px-4 py-3">
                          {isSweepGroup ? (
                            <button
                              type="button"
                              onClick={() => toggleSweepExpanded(run.run_id)}
                              className="app-button-secondary inline-flex h-8 w-8 items-center justify-center rounded-lg p-0 transition"
                              aria-expanded={isExpanded}
                              aria-label={isExpanded ? 'Collapse sweep variants' : 'Expand sweep variants'}
                              title={isExpanded ? 'Collapse sweep variants' : 'Expand sweep variants'}
                            >
                              <ChevronIcon expanded={isExpanded} />
                            </button>
                          ) : (
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={!checked && selectionLimitReached}
                              onChange={() => toggleResult(resultRef)}
                              className="app-checkbox h-4 w-4 rounded disabled:cursor-not-allowed disabled:opacity-40"
                            />
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold app-title">
                              {formatComparableRunLabel(run)}
                            </span>
                            {isSweepGroup ? (
                              <span className="app-badge rounded-full px-2 py-0.5 text-[11px] font-semibold">
                                Parameter sweep · {variantCount} variants
                              </span>
                            ) : null}
                          </div>
                          <div className="mt-1 text-xs app-text-soft">
                            {isSweepGroup
                              ? 'Expand to select variants'
                              : isSavedSweepVariantResult(run)
                                ? formatSavedSweepVariantSource(run)
                                : run.run_id}
                          </div>
                        </td>
                        <td className="px-4 py-3 app-text-muted">{isSweepGroup ? '—' : formatPct(run.total_return_pct)}</td>
                        <td className="px-4 py-3 app-text-muted">{isSweepGroup ? '—' : formatNumber(run.sharpe_ratio)}</td>
                        <td className="px-4 py-3 app-text-muted">{isSweepGroup ? '—' : formatPct(run.max_drawdown_pct)}</td>
                      </tr>
                      {isSweepGroup && isExpanded
                        ? run.sweep_variants.map((variant) => {
                            const variantChecked = selectedResultRefs.includes(variant.comparable_result_ref);
                            const rankLabel = variant.rank ? `Rank #${variant.rank}` : 'Variant';
                            const parameterLabel = formatParameterSummary(variant.parameters);
                            return (
                              <tr key={variant.comparable_result_ref} className="app-row-hover bg-black/[0.025] dark:bg-white/[0.035]">
                                <td className="px-4 py-3">
                                  <div className="flex items-center gap-3 pl-5">
                                    <span className="h-8 w-1 rounded-full bg-cyan-500/70" aria-hidden="true" />
                                    <input
                                      type="checkbox"
                                      checked={variantChecked}
                                      disabled={!variantChecked && selectionLimitReached}
                                      onChange={() => toggleResult(variant.comparable_result_ref)}
                                      className="app-checkbox h-4 w-4 rounded disabled:cursor-not-allowed disabled:opacity-40"
                                    />
                                  </div>
                                </td>
                                <td className="px-4 py-3 pl-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="app-badge rounded-full px-2 py-0.5 text-[11px] font-semibold">
                                      {rankLabel}
                                    </span>
                                    <span className="font-medium app-title">
                                      {variant.label}
                                    </span>
                                  </div>
                                  <div className="mt-1 text-xs app-text-soft">
                                    Variant · {parameterLabel}
                                  </div>
                                </td>
                                <td className="px-4 py-3 app-text-muted">{formatPct(variant.total_return_pct)}</td>
                                <td className="px-4 py-3 app-text-muted">{formatNumber(variant.sharpe_ratio)}</td>
                                <td className="px-4 py-3 app-text-muted">{formatPct(variant.max_drawdown_pct)}</td>
                              </tr>
                            );
                          })
                        : null}
                    </Fragment>
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
