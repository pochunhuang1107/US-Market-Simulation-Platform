import type { ReactNode } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';

import {
  formatCurrency,
  formatMonthLabel,
  formatPct,
  formatShortDate
} from '../../lib/formatters';
import type {
  RunChartDataResponse,
  RunResponse,
  SleeveEquityPoint,
  SleeveWeightPoint
} from '../../types/api';
import { SectionCard } from '../shared/SectionCard';
import { inferBenchmarkLabel } from './RunInsightHero';

const chartTooltipStyle = {
  background: 'var(--surface-strong)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  color: 'var(--title)'
};

const VALUE_EPSILON = 0.000001;
const WEIGHT_EPSILON = 0.01;

export function RunCharts({ chartData, run }: { chartData: RunChartDataResponse; run: RunResponse }) {
  const benchmarkDrawdownLabel = `${inferBenchmarkLabel(run, chartData) ?? 'Benchmark'} drawdown`;
  const hasDrawdownData = chartData.drawdown_curve.length > 0;
  const hasMonthlyReturnData = chartData.monthly_returns.length > 0;
  const hasSleeveEquityData = hasMeaningfulSleeveEquity(chartData.sleeve_equity_curve, run);
  const hasSleeveWeightData = hasMeaningfulSleeveAllocation(chartData.sleeve_weight_curve, run);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        {hasDrawdownData ? (
          <SectionCard
            title="Drawdown Comparison"
            subtitle="How far the strategy and benchmark fell from previous highs."
          >
            <ChartFrame>
              <ResponsiveContainer>
                <LineChart data={chartData.drawdown_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
                  <YAxis tickFormatter={formatPct} stroke="var(--text-muted)" width={80} />
                  <Tooltip
                    formatter={(value, name) => [formatPct(Number(value ?? 0)), String(name ?? '')]}
                    labelFormatter={(label) => formatShortDate(label)}
                    contentStyle={chartTooltipStyle}
                  />
                  <Legend />
                  <ReferenceLine y={0} stroke="var(--border)" />
                  <Line
                    type="monotone"
                    dataKey="strategy_drawdown_pct"
                    name="Strategy drawdown"
                    stroke="#e11d48"
                    strokeWidth={2.25}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="benchmark_drawdown_pct"
                    name={benchmarkDrawdownLabel}
                    stroke="#f59e0b"
                    strokeWidth={2.25}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </ChartFrame>
          </SectionCard>
        ) : null}

        {hasSleeveEquityData ? (
          <SectionCard title="Sleeve Performance" subtitle="Core and overlay sleeve equity over time.">
            <ChartFrame>
              <ResponsiveContainer>
                <LineChart data={chartData.sleeve_equity_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
                  <YAxis tickFormatter={formatCurrency} stroke="var(--text-muted)" width={96} />
                  <Tooltip
                    formatter={(value, name) => [formatCurrency(Number(value ?? 0)), String(name ?? '')]}
                    labelFormatter={(label) => formatShortDate(label)}
                    contentStyle={chartTooltipStyle}
                  />
                  <Legend />
                  <Line type="monotone" dataKey="core_equity" name="Core sleeve" stroke="#22c55e" strokeWidth={2.25} dot={false} />
                  <Line type="monotone" dataKey="overlay_equity" name="Overlay sleeve" stroke="#f59e0b" strokeWidth={2.25} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartFrame>
          </SectionCard>
        ) : null}

        {hasMonthlyReturnData ? (
          <SectionCard title="Monthly Strategy Returns" subtitle="Strategy return by month.">
            <ChartFrame>
              <ResponsiveContainer>
                <BarChart data={chartData.monthly_returns} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tickFormatter={formatMonthLabel} minTickGap={24} stroke="var(--text-muted)" />
                  <YAxis tickFormatter={formatPct} stroke="var(--text-muted)" width={80} />
                  <Tooltip
                    formatter={(value) => [formatPct(Number(value ?? 0)), 'Strategy return']}
                    labelFormatter={(label) => formatMonthLabel(label)}
                    contentStyle={chartTooltipStyle}
                  />
                  <ReferenceLine y={0} stroke="var(--border)" />
                  <Bar dataKey="return_pct" name="Strategy return" fill="#06b6d4" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartFrame>
          </SectionCard>
        ) : null}

        {hasSleeveWeightData ? (
          <SectionCard title="Sleeve Allocation" subtitle="Core and overlay allocation through the result.">
            <ChartFrame>
              <ResponsiveContainer>
                <LineChart data={chartData.sleeve_weight_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
                  <YAxis tickFormatter={formatPct} stroke="var(--text-muted)" width={80} />
                  <Tooltip
                    formatter={(value, name) => [formatPct(Number(value ?? 0)), String(name ?? '')]}
                    labelFormatter={(label) => formatShortDate(label)}
                    contentStyle={chartTooltipStyle}
                  />
                  <Legend />
                  <Line type="monotone" dataKey="core_weight_pct" name="Core allocation" stroke="#4ade80" strokeWidth={2.25} dot={false} />
                  <Line type="monotone" dataKey="overlay_weight_pct" name="Overlay allocation" stroke="#fbbf24" strokeWidth={2.25} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartFrame>
          </SectionCard>
        ) : null}
      </div>

      <SectionCard title="Trade Events" subtitle="Buy and sell events generated by this result.">
        <div className="app-table-frame max-h-[420px] overflow-auto rounded-2xl">
          <table className="min-w-full divide-y text-sm app-divider">
            <thead className="app-table-head sticky top-0 text-left text-xs font-semibold uppercase tracking-[0.18em]">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3">Shares</th>
                <th className="px-4 py-3">Price</th>
              </tr>
            </thead>
            <tbody className="app-table-body divide-y app-divider">
              {chartData.trade_markers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="app-text-muted px-4 py-12 text-center">
                    No trade markers were available for this result.
                  </td>
                </tr>
              ) : (
                chartData.trade_markers.map((trade, index) => (
                  <tr key={`${trade.date}-${trade.side}-${index}`} className="app-row-hover">
                    <td className="px-4 py-3">{formatShortDate(trade.date)}</td>
                    <td className="app-title px-4 py-3 font-medium">{trade.side}</td>
                    <td className="px-4 py-3">{trade.shares ?? '—'}</td>
                    <td className="px-4 py-3">{trade.price?.toFixed(2) ?? '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function ChartFrame({ children }: { children: ReactNode }) {
  return <div className="chart-frame h-[340px] w-full select-none">{children}</div>;
}

function hasMeaningfulSleeveEquity(points: SleeveEquityPoint[], run: RunResponse) {
  if (isCoreOverlayDisabled(run) || points.length === 0) {
    return false;
  }

  if (isCoreOverlayEnabled(run)) {
    return points.some((point) => point.core_equity != null || point.overlay_equity != null);
  }

  const hasCoreEquity = points.some((point) => isMeaningfulValue(point.core_equity));
  const hasOverlayEquity = points.some((point) => isMeaningfulValue(point.overlay_equity));

  return hasCoreEquity && hasOverlayEquity;
}

function hasMeaningfulSleeveAllocation(points: SleeveWeightPoint[], run: RunResponse) {
  if (isCoreOverlayDisabled(run) || points.length === 0) {
    return false;
  }

  const coreWeights = points.map((point) => point.core_weight_pct).filter(isFiniteNumber);
  const overlayWeights = points.map((point) => point.overlay_weight_pct).filter(isFiniteNumber);

  if (coreWeights.length === 0 && overlayWeights.length === 0) {
    return false;
  }

  const hasMeaningfulCore = coreWeights.some((weight) => weight > WEIGHT_EPSILON);
  const hasMeaningfulOverlay = overlayWeights.some((weight) => weight > WEIGHT_EPSILON && weight < 100 - WEIGHT_EPSILON);
  const isDefaultSingleSleeve =
    coreWeights.every((weight) => Math.abs(weight) <= WEIGHT_EPSILON) &&
    overlayWeights.every((weight) => Math.abs(weight - 100) <= WEIGHT_EPSILON);

  if (isDefaultSingleSleeve) {
    return false;
  }

  if (isCoreOverlayEnabled(run)) {
    return true;
  }

  return (
    (hasMeaningfulCore && hasMeaningfulOverlay) ||
    hasMeaningfulWeightChange(coreWeights) ||
    hasMeaningfulWeightChange(overlayWeights)
  );
}

function isCoreOverlayEnabled(run: RunResponse) {
  const coreOverlay = getCoreOverlayConfig(run);
  const enabled = coreOverlay?.enabled;
  const coreAllocation = toFiniteNumber(coreOverlay?.core_allocation_pct);

  return enabled === true && (coreAllocation === null || coreAllocation > VALUE_EPSILON);
}

function isCoreOverlayDisabled(run: RunResponse) {
  const coreOverlay = getCoreOverlayConfig(run);
  const enabled = coreOverlay?.enabled;
  const coreAllocation = toFiniteNumber(coreOverlay?.core_allocation_pct);

  return enabled === false || (enabled === true && coreAllocation !== null && coreAllocation <= VALUE_EPSILON);
}

function getCoreOverlayConfig(run: RunResponse) {
  const requestPayload = run.request_payload;
  const draftConfig = requestPayload?.draft_config;

  if (!isRecord(draftConfig)) {
    return null;
  }

  const coreOverlay = draftConfig.core_overlay;

  return isRecord(coreOverlay) ? coreOverlay : null;
}

function hasMeaningfulWeightChange(weights: number[]) {
  if (weights.length < 2) {
    return false;
  }

  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);

  return maxWeight - minWeight > WEIGHT_EPSILON;
}

function isMeaningfulValue(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) > VALUE_EPSILON;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function toFiniteNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
