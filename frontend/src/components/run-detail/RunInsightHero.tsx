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
import { formatTradeActivity } from '../../lib/sweepVariants';
import type { RunChartDataResponse, RunResponse } from '../../types/api';

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

const tooltipStyle = {
  background: 'var(--surface-strong)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  color: 'var(--title)'
};

export function RunInsightHero({
  run,
  chartData
}: {
  run: RunResponse;
  chartData: RunChartDataResponse;
}) {
  const summary = run.summary_json ?? {};

  const totalReturnPct = getSummaryNumber(summary, 'total_return_pct');
  const benchmarkReturnPct = getSummaryNumber(summary, 'benchmark_return_pct');
  const alphaPct = getSummaryNumber(summary, 'alpha_vs_benchmark_pct');
  const cagrPct = getSummaryNumber(summary, 'cagr_pct');
  const maxDrawdownPct = getSummaryNumber(summary, 'max_drawdown_pct');
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

  if (cagrPct !== null) {
    metrics.push({
      label: 'CAGR',
      value: formatPct(cagrPct),
      tone: getTone(cagrPct)
    });
  }

  metrics.push(
    {
      label: 'Max Drawdown',
      value: formatPct(maxDrawdownPct),
      tone: 'negative'
    },
    {
      label: 'Trades',
      value: formatTradeActivity(summary)
    }
  );

  if (alphaPct !== null) {
    metrics.push({
      label: 'Alpha',
      value: formatPct(alphaPct),
      tone: getTone(alphaPct)
    });
  }

  const strategyName = run.strategy_name ?? 'Draft strategy';

  return (
    <section className="app-card app-shadow rounded-[32px] border p-5">
      <div className="grid gap-6 xl:grid-cols-[1.1fr_1.6fr]">
        <div className="space-y-5">
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

        <div className="app-surface-soft rounded-3xl border p-4">
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

          <div className="h-[360px] w-full">
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
      </div>
    </section>
  );
}
