import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';

import {
  formatCurrency,
  formatPct,
  formatShortDate
} from '../../lib/formatters';
import {
  buildModelSignalRunContext,
  formatModelSignalList
} from '../../lib/modelSignalRunContext';
import { formatTradeActivity } from '../../lib/sweepVariants';
import type { ModelSignalCatalogItemResponse, RunChartDataResponse, RunResponse } from '../../types/api';

type MetricTone = 'default' | 'positive' | 'negative';

type HeroMetric = {
  label: string;
  value: string;
  tone?: MetricTone;
};

const BENCHMARK_SYMBOL_KEYS = ['benchmark_symbol', 'benchmark_ticker', 'benchmark'];
const BENCHMARK_NAME_KEYS = ['benchmark_name', 'benchmark_label'];

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function getSummaryNumber(summary: Record<string, unknown>, key: string): number | null {
  return toNumber(summary[key]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function cleanBenchmarkValue(value: unknown): string | null {
  if (typeof value !== 'string') return null;

  const cleaned = value.trim();
  const normalized = cleaned.toLowerCase();
  if (!cleaned || normalized === 'benchmark' || normalized === 'benchmark_equity') {
    return null;
  }

  return cleaned;
}

function findBenchmarkValue(source: unknown, keys: string[]): string | null {
  if (!isRecord(source)) return null;

  for (const key of keys) {
    const value = cleanBenchmarkValue(source[key]);
    if (value !== null) return value;
  }

  return null;
}

export function inferBenchmarkLabel(run: RunResponse, chartData: RunChartDataResponse): string | null {
  const requestPayload = run.request_payload ?? {};
  const draftConfig = isRecord(requestPayload) ? requestPayload.draft_config : null;
  const sources: unknown[] = [run.summary_json, draftConfig, requestPayload, chartData];

  for (const source of sources) {
    const symbol = findBenchmarkValue(source, BENCHMARK_SYMBOL_KEYS);
    if (symbol !== null) return symbol.toUpperCase();

    const name = findBenchmarkValue(source, BENCHMARK_NAME_KEYS);
    if (name !== null) return name;
  }

  return null;
}

function getTone(value: number | null, positiveIsGood = true): MetricTone {
  if (value === null || value === 0) return 'default';

  if (positiveIsGood) {
    return value > 0 ? 'positive' : 'negative';
  }

  return value < 0 ? 'negative' : 'positive';
}

function MetricPill({ metric }: { metric: HeroMetric }) {
  const toneClass =
    metric.tone === 'positive'
      ? 'text-emerald-500 dark:text-emerald-300'
      : metric.tone === 'negative'
        ? 'text-rose-500 dark:text-rose-300'
        : 'app-title';

  return (
    <div className="app-surface-soft rounded-2xl border px-4 py-3">
      <div className="app-label text-[11px] font-semibold uppercase tracking-[0.2em]">
        {metric.label}
      </div>
      <div className={`mt-2 text-xl font-semibold ${toneClass}`}>{metric.value}</div>
    </div>
  );
}

function VerdictBadge({
  label,
  tone
}: {
  label: string;
  tone: MetricTone;
}) {
  const className =
    tone === 'positive'
      ? 'app-chip-success'
      : tone === 'negative'
        ? 'app-chip-warning'
        : 'app-chip-info';

  return (
    <span className={`${className} rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em]`}>
      {label}
    </span>
  );
}

function ModelSignalContextPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="app-surface-soft rounded-2xl border px-3 py-2">
      <div className="app-label text-[10px] font-semibold uppercase tracking-[0.16em]">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold app-title">{value}</div>
    </div>
  );
}

const tooltipStyle = {
  background: 'var(--surface-strong)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  color: 'var(--title)'
};

function EquityChartCard({
  chartData,
  benchmarkLabel,
  benchmarkDisplayLabel,
  compact = false
}: {
  chartData: RunChartDataResponse;
  benchmarkLabel: string | null;
  benchmarkDisplayLabel: string;
  compact?: boolean;
}) {
  return (
    <div className="app-surface-soft h-fit min-h-0 self-start rounded-3xl border p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
            Strategy vs {benchmarkLabel ?? 'benchmark'}
          </div>
          <p className="app-text-muted mt-1 text-sm">
            Equity growth over the selected backtest window.
          </p>
        </div>
      </div>

      <div className={`${compact ? 'h-[320px]' : 'h-[360px]'} w-full`}>
        <ResponsiveContainer>
          <LineChart
            data={chartData.equity_curve}
            margin={{ top: 8, right: 16, left: 4, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickFormatter={formatShortDate}
              minTickGap={36}
              stroke="var(--text-muted)"
            />
            <YAxis
              tickFormatter={formatCurrency}
              stroke="var(--text-muted)"
              width={96}
            />
            <Tooltip
              formatter={(value, name) => [
                formatCurrency(typeof value === 'number' ? value : null),
                name === 'Strategy' ? 'Strategy' : benchmarkDisplayLabel
              ]}
              labelFormatter={(label) => formatShortDate(String(label))}
              contentStyle={tooltipStyle}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="strategy_equity"
              name="Strategy"
              stroke="#06b6d4"
              strokeWidth={2.5}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="benchmark_equity"
              name={benchmarkDisplayLabel}
              stroke="#a855f7"
              strokeWidth={2.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function RunInsightHero({
  run,
  chartData,
  modelSignalCatalogItem = null,
  latestRebalanceSelection = []
}: {
  run: RunResponse;
  chartData: RunChartDataResponse;
  modelSignalCatalogItem?: ModelSignalCatalogItemResponse | null;
  latestRebalanceSelection?: string[];
}) {
  const summary = run.summary_json ?? {};
  const modelSignalContext = buildModelSignalRunContext(run, modelSignalCatalogItem);

  const totalReturnPct = getSummaryNumber(summary, 'total_return_pct');
  const benchmarkReturnPct = getSummaryNumber(summary, 'benchmark_return_pct');
  const alphaPct = getSummaryNumber(summary, 'alpha_vs_benchmark_pct');
  const universeEqualWeightReturnPct =
    getSummaryNumber(summary, 'universe_equal_weight_return_pct') ??
    getSummaryNumber(summary, 'universe_equal_weight_buy_hold_return_pct');
  const alphaVsUniverseEqualWeightPct = getSummaryNumber(summary, 'alpha_vs_universe_equal_weight_pct');
  const cagrPct = getSummaryNumber(summary, 'cagr_pct');
  const maxDrawdownPct = getSummaryNumber(summary, 'max_drawdown_pct');
  const rebalanceCount = getSummaryNumber(summary, 'rebalance_count');
  const isRotationRun = summary.strategy_type === 'rotation';
  const benchmarkLabel = inferBenchmarkLabel(run, chartData);
  const benchmarkDisplayLabel = benchmarkLabel ?? 'Benchmark';

  const verdictLabel =
    alphaPct !== null
      ? alphaPct > 0
        ? 'Outperformed benchmark'
        : alphaPct < 0
          ? 'Underperformed benchmark'
          : 'Matched benchmark'
      : totalReturnPct !== null
        ? totalReturnPct >= 0
          ? 'Positive return'
          : 'Negative return'
        : 'Result ready';
  const verdictTone = getTone(alphaPct ?? totalReturnPct);

  const metrics: HeroMetric[] = [
    {
      label: 'Total Return',
      value: formatPct(totalReturnPct),
      tone: getTone(totalReturnPct)
    }
  ];

  if (benchmarkReturnPct !== null) {
    metrics.push({
      label: benchmarkLabel ? `Benchmark (${benchmarkLabel})` : 'Benchmark',
      value: formatPct(benchmarkReturnPct),
      tone: getTone(benchmarkReturnPct)
    });
  }

  if (universeEqualWeightReturnPct !== null) {
    metrics.push({
      label: 'Equal-Weight Universe',
      value: formatPct(universeEqualWeightReturnPct),
      tone: getTone(universeEqualWeightReturnPct)
    });
  }

  if (cagrPct !== null) {
    metrics.push({
      label: 'CAGR',
      value: formatPct(cagrPct),
      tone: getTone(cagrPct)
    });
  }

  metrics.push({
    label: 'Max Drawdown',
    value: formatPct(maxDrawdownPct),
    tone: 'negative'
  });

  if (isRotationRun && rebalanceCount !== null) {
    metrics.push({
      label: 'Rebalances',
      value: formatTradeActivity({ trade_count: rebalanceCount })
    });
  } else {
    metrics.push({
      label: 'Trades',
      value: formatTradeActivity(summary)
    });
  }

  if (alphaVsUniverseEqualWeightPct !== null) {
    metrics.push({
      label: 'Universe Alpha',
      value: formatPct(alphaVsUniverseEqualWeightPct),
      tone: getTone(alphaVsUniverseEqualWeightPct)
    });
  }

  if (alphaPct !== null) {
    metrics.push({
      label: 'Alpha',
      value: formatPct(alphaPct),
      tone: getTone(alphaPct)
    });
  }

  const strategyName = run.strategy_name ?? (modelSignalContext ? modelSignalContext.displayName ?? 'Model signal strategy' : 'Draft strategy');
  const isModelSignalHero = Boolean(modelSignalContext);
  const modelSignalFields = modelSignalContext
    ? [
        modelSignalContext.modelVersion ? { label: 'Model version', value: modelSignalContext.modelVersion } : null,
        modelSignalContext.latestSignalDate ? { label: 'Signal date', value: modelSignalContext.latestSignalDate } : null,
        modelSignalContext.rankingField ? { label: 'Ranking field', value: modelSignalContext.rankingField } : null,
        modelSignalContext.topN !== null ? { label: 'Top N', value: String(modelSignalContext.topN) } : null,
        { label: 'Signal bucket', value: formatModelSignalList(modelSignalContext.signalBucketFilter) },
        modelSignalContext.fallback ? { label: 'Fallback', value: modelSignalContext.fallback } : null,
        latestRebalanceSelection.length > 0
          ? { label: 'Latest rebalance holding', value: latestRebalanceSelection.join(', ') }
          : null,
        modelSignalContext.researchStatus ? { label: 'Paper tracking', value: modelSignalContext.researchStatus } : null
      ].filter((field): field is { label: string; value: string } => Boolean(field))
    : [];

  if (isModelSignalHero && modelSignalContext) {
    return (
      <section className="app-card app-shadow rounded-[32px] border p-5">
        <div>
          <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
            Completed result
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <h2 className="app-title text-2xl font-semibold tracking-tight">
              {strategyName}
            </h2>
            <VerdictBadge label="Model signal strategy" tone="default" />
            <VerdictBadge label={verdictLabel} tone={verdictTone} />
          </div>
        </div>

        <div className="app-surface-soft mt-5 rounded-3xl border p-4">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {modelSignalFields.map((field) => (
              <ModelSignalContextPill key={field.label} label={field.label} value={field.value} />
            ))}
          </div>
          <p className="mt-3 text-xs app-text-muted">
            Research-only paper-tracking signal; not investment advice.
          </p>
        </div>

        <div className="mt-5 grid items-start gap-6 auto-rows-max xl:grid-cols-[minmax(320px,0.9fr)_minmax(0,1.65fr)]">
          <div className="grid self-start gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            {metrics.map((metric) => (
              <MetricPill key={metric.label} metric={metric} />
            ))}
          </div>

          <EquityChartCard
            chartData={chartData}
            benchmarkLabel={benchmarkLabel}
            benchmarkDisplayLabel={benchmarkDisplayLabel}
            compact
          />
        </div>
      </section>
    );
  }

  return (
    <section className="app-card app-shadow rounded-[32px] border p-5">
      <div className="grid items-start gap-6 auto-rows-max xl:grid-cols-[1.1fr_1.6fr]">
        <div className="self-start space-y-5">
          <div>
            <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
              Completed result
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <h2 className="app-title text-2xl font-semibold tracking-tight">
                {strategyName}
              </h2>
              <VerdictBadge label={verdictLabel} tone={verdictTone} />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            {metrics.map((metric) => (
              <MetricPill key={metric.label} metric={metric} />
            ))}
          </div>
        </div>

        <EquityChartCard
          chartData={chartData}
          benchmarkLabel={benchmarkLabel}
          benchmarkDisplayLabel={benchmarkDisplayLabel}
        />
      </div>
    </section>
  );
}
