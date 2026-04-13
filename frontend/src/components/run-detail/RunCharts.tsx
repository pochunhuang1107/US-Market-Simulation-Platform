import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
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
  formatShortDate,
  humanizeSeriesName
} from '../../lib/formatters';
import type { EquityCurvePoint, RunChartDataResponse } from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

const chartTooltipStyle = {
  background: 'var(--surface-strong)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  color: 'var(--title)'
};

type RechartsPointerState = {
  activeTooltipIndex?: number | string | null;
};

type RangeMeasurement = {
  start: EquityCurvePoint;
  end: EquityCurvePoint;
  tradingDays: number;
  strategyReturnPct: number;
  benchmarkReturnPct: number | null;
  alphaPct: number | null;
};

type EquityTooltipContentProps = {
  active?: boolean;
  label?: string;
  payload?: Array<{
    value?: number | null;
    name?: string;
    dataKey?: string;
  }>;
  measurement: RangeMeasurement | null;
};

const strategyActiveDot = {
  r: 4,
  fill: '#06b6d4',
  stroke: 'none',
  strokeWidth: 0
};

const benchmarkActiveDot = {
  r: 4,
  fill: '#a855f7',
  stroke: 'none',
  strokeWidth: 0
};

export function RunCharts({ chartData }: { chartData: RunChartDataResponse }) {
  const [anchorIndex, setAnchorIndex] = useState<number | null>(null);
  const [currentIndex, setCurrentIndex] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const measurement = useMemo(() => {
    if (!isDragging || anchorIndex === null || currentIndex === null || anchorIndex === currentIndex) {
      return null;
    }

    const startIndex = Math.min(anchorIndex, currentIndex);
    const endIndex = Math.max(anchorIndex, currentIndex);
    const start = chartData.equity_curve[startIndex];
    const end = chartData.equity_curve[endIndex];

    if (!start || !end) {
      return null;
    }

    return buildRangeMeasurement(start, end, startIndex, endIndex);
  }, [anchorIndex, chartData.equity_curve, currentIndex, isDragging]);

  const getActiveIndex = (state?: RechartsPointerState): number | null => {
    const raw = state?.activeTooltipIndex;

    if (typeof raw === 'number' && Number.isFinite(raw)) {
      return raw;
    }

    if (typeof raw === 'string') {
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : null;
    }

    return null;
  };

  const handleEquityMouseDown = (state?: RechartsPointerState) => {
    const nextIndex = getActiveIndex(state);
    if (nextIndex === null) {
      return;
    }

    setAnchorIndex(nextIndex);
    setCurrentIndex(nextIndex);
    setIsDragging(true);
  };

  const handleEquityMouseMove = (state?: RechartsPointerState) => {
    const nextIndex = getActiveIndex(state);
    if (nextIndex === null) {
      return;
    }

    if (isDragging) {
      setCurrentIndex(nextIndex);
    }
  };

  const handleEquityMouseUp = () => {
    setIsDragging(false);
    setAnchorIndex(null);
    setCurrentIndex(null);
  };

  return (
    <div className="space-y-6">
      <SectionCard title="Equity Curve" subtitle="Strategy and benchmark equity extracted from timeline artifacts.">
        <ChartFrame>
          <ResponsiveContainer>
            <LineChart
              data={chartData.equity_curve}
              margin={{ top: 8, right: 16, left: 4, bottom: 0 }}
              onMouseDown={(state) => handleEquityMouseDown(state as RechartsPointerState)}
              onMouseMove={(state) => handleEquityMouseMove(state as RechartsPointerState)}
              onMouseUp={handleEquityMouseUp}
              onMouseLeave={handleEquityMouseUp}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
              <YAxis tickFormatter={formatCurrency} stroke="var(--text-muted)" width={96} />
              <Tooltip
                content={<EquityTooltipContent measurement={measurement} />}
                contentStyle={chartTooltipStyle}
              />
              <Legend />
              {measurement ? (
                <>
                  <ReferenceArea
                    x1={measurement.start.date}
                    x2={measurement.end.date}
                    fill="var(--range-selection-fill)"
                    fillOpacity={1}
                    strokeOpacity={0}
                    ifOverflow="extendDomain"
                  />
                  <ReferenceLine
                    x={measurement.start.date}
                    stroke="var(--range-selection-line)"
                    strokeDasharray="4 4"
                    strokeWidth={1.5}
                    ifOverflow="extendDomain"
                  />
                  <ReferenceLine
                    x={measurement.end.date}
                    stroke="var(--range-selection-line)"
                    strokeDasharray="4 4"
                    strokeWidth={1.5}
                    ifOverflow="extendDomain"
                  />
                </>
              ) : null}
              <Line
                type="monotone"
                dataKey="strategy_equity"
                name="strategy_equity"
                stroke="#06b6d4"
                strokeWidth={2.25}
                dot={false}
                activeDot={strategyActiveDot}
              />
              <Line
                type="monotone"
                dataKey="benchmark_equity"
                name="benchmark_equity"
                stroke="#a855f7"
                strokeWidth={2.25}
                dot={false}
                activeDot={benchmarkActiveDot}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartFrame>
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="Drawdown Curve" subtitle="Strategy and benchmark drawdown series.">
          <ChartFrame>
            <ResponsiveContainer>
              <LineChart data={chartData.drawdown_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
                <YAxis tickFormatter={formatPct} stroke="var(--text-muted)" width={80} />
                <Tooltip
                  formatter={(value, name) => [formatPct(Number(value ?? 0)), humanizeSeriesName(String(name ?? ''))]}
                  labelFormatter={(label) => formatShortDate(label)}
                  contentStyle={chartTooltipStyle}
                />
                <Legend />
                <ReferenceLine y={0} stroke="var(--border)" />
                <Line
                  type="monotone"
                  dataKey="strategy_drawdown_pct"
                  name="strategy_drawdown_pct"
                  stroke="#e11d48"
                  strokeWidth={2.25}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="benchmark_drawdown_pct"
                  name="benchmark_drawdown_pct"
                  stroke="#f59e0b"
                  strokeWidth={2.25}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>

        <SectionCard title="Sleeve Equity" subtitle="Core and overlay sleeve equity over time.">
          <ChartFrame>
            <ResponsiveContainer>
              <LineChart data={chartData.sleeve_equity_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
                <YAxis tickFormatter={formatCurrency} stroke="var(--text-muted)" width={96} />
                <Tooltip
                  formatter={(value, name) => [formatCurrency(Number(value ?? 0)), humanizeSeriesName(String(name ?? ''))]}
                  labelFormatter={(label) => formatShortDate(label)}
                  contentStyle={chartTooltipStyle}
                />
                <Legend />
                <Line type="monotone" dataKey="core_equity" name="core_equity" stroke="#22c55e" strokeWidth={2.25} dot={false} />
                <Line type="monotone" dataKey="overlay_equity" name="overlay_equity" stroke="#f59e0b" strokeWidth={2.25} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="Monthly Returns" subtitle="Month-over-month strategy returns from report artifacts.">
          <ChartFrame>
            <ResponsiveContainer>
              <BarChart data={chartData.monthly_returns} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" tickFormatter={formatMonthLabel} minTickGap={24} stroke="var(--text-muted)" />
                <YAxis tickFormatter={formatPct} stroke="var(--text-muted)" width={80} />
                <Tooltip
                  formatter={(value) => [formatPct(Number(value ?? 0)), 'Return']}
                  labelFormatter={(label) => formatMonthLabel(label)}
                  contentStyle={chartTooltipStyle}
                />
                <ReferenceLine y={0} stroke="var(--border)" />
                <Bar dataKey="return_pct" name="return_pct" fill="#06b6d4" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>

        <SectionCard title="Sleeve Weights" subtitle="Core and overlay weights through the run.">
          <ChartFrame>
            <ResponsiveContainer>
              <LineChart data={chartData.sleeve_weight_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
                <YAxis tickFormatter={formatPct} stroke="var(--text-muted)" width={80} />
                <Tooltip
                  formatter={(value, name) => [formatPct(Number(value ?? 0)), humanizeSeriesName(String(name ?? ''))]}
                  labelFormatter={(label) => formatShortDate(label)}
                  contentStyle={chartTooltipStyle}
                />
                <Legend />
                <Line type="monotone" dataKey="core_weight_pct" name="core_weight_pct" stroke="#4ade80" strokeWidth={2.25} dot={false} />
                <Line type="monotone" dataKey="overlay_weight_pct" name="overlay_weight_pct" stroke="#fbbf24" strokeWidth={2.25} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>
      </div>

      <SectionCard title="Trade Markers" subtitle="Artifact-derived trade events aligned to run dates.">
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
                    No trade markers were available for this run.
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

function EquityTooltipContent({ active, label, payload, measurement }: EquityTooltipContentProps) {
  if (!active) {
    return null;
  }

  if (measurement) {
    return (
      <div style={chartTooltipStyle} className="min-w-[240px] space-y-2 px-4 py-3 shadow-lg">
        <div className="app-title text-sm font-semibold">
          {formatShortDate(measurement.start.date)} → {formatShortDate(measurement.end.date)}
        </div>
        <div className="app-text-muted text-xs">{measurement.tradingDays} chart points</div>
        <div className="space-y-1 text-sm">
          <div className="flex items-center justify-between gap-4">
            <span className="app-text-muted">Strategy</span>
            <span className={measurement.strategyReturnPct >= 0 ? 'font-semibold text-emerald-500' : 'font-semibold text-rose-500'}>
              {formatPct(measurement.strategyReturnPct)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="app-text-muted">Benchmark</span>
            <span className={measurement.benchmarkReturnPct !== null && measurement.benchmarkReturnPct >= 0 ? 'font-semibold text-emerald-500' : 'font-semibold text-rose-500'}>
              {measurement.benchmarkReturnPct === null ? '—' : formatPct(measurement.benchmarkReturnPct)}
            </span>
          </div>
          <div className="app-divider flex items-center justify-between gap-4 border-t pt-2">
            <span className="app-text-muted">Edge</span>
            <span className={measurement.alphaPct !== null && measurement.alphaPct >= 0 ? 'font-semibold text-emerald-500' : 'font-semibold text-rose-500'}>
              {measurement.alphaPct === null ? '—' : formatPct(measurement.alphaPct)}
            </span>
          </div>
        </div>
      </div>
    );
  }

  const strategyValue = payload?.find((entry) => entry.dataKey === 'strategy_equity')?.value;
  const benchmarkValue = payload?.find((entry) => entry.dataKey === 'benchmark_equity')?.value;

  return (
    <div style={chartTooltipStyle} className="min-w-[220px] space-y-2 px-4 py-3 shadow-lg">
      <div className="app-title text-sm font-semibold">{label ? formatShortDate(label) : '—'}</div>
      <div className="space-y-1 text-sm">
        <div className="flex items-center justify-between gap-4">
          <span className="app-text-muted">Strategy</span>
          <span className="font-semibold text-cyan-500">
            {formatCurrency(typeof strategyValue === 'number' ? strategyValue : null)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="app-text-muted">Benchmark</span>
          <span className="font-semibold text-violet-500">
            {formatCurrency(typeof benchmarkValue === 'number' ? benchmarkValue : null)}
          </span>
        </div>
      </div>
    </div>
  );
}

function buildRangeMeasurement(start: EquityCurvePoint, end: EquityCurvePoint, anchorIndex: number, currentIndex: number) {
  const strategyReturnPct = calculateReturnPct(start.strategy_equity, end.strategy_equity);
  const benchmarkReturnPct =
    start.benchmark_equity !== null && end.benchmark_equity !== null
      ? calculateReturnPct(start.benchmark_equity, end.benchmark_equity)
      : null;

  return {
    start,
    end,
    tradingDays: Math.abs(currentIndex - anchorIndex) + 1,
    strategyReturnPct,
    benchmarkReturnPct,
    alphaPct: benchmarkReturnPct === null ? null : strategyReturnPct - benchmarkReturnPct
  };
}

function calculateReturnPct(startValue: number, endValue: number) {
  if (!Number.isFinite(startValue) || !Number.isFinite(endValue) || startValue === 0) {
    return 0;
  }

  return ((endValue / startValue) - 1) * 100;
}

function ChartFrame({ children }: { children: React.ReactNode }) {
  return <div className="chart-frame h-[340px] w-full select-none">{children}</div>;
}