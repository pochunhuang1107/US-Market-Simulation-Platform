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
  formatShortDate,
  humanizeSeriesName
} from '../../lib/formatters';
import type { RunChartDataResponse } from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

const chartTooltipStyle = {
  background: 'var(--surface-strong)',
  border: '1px solid var(--border)',
  borderRadius: 16,
  color: 'var(--title)'
};

export function RunCharts({ chartData }: { chartData: RunChartDataResponse }) {
  return (
    <div className="space-y-6">
      <SectionCard
        title="Equity Curve"
        subtitle="Strategy and benchmark equity extracted from timeline artifacts."
      >
        <ChartFrame>
          <ResponsiveContainer>
            <LineChart data={chartData.equity_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="var(--text-muted)" />
              <YAxis tickFormatter={formatCurrency} stroke="var(--text-muted)" width={96} />
              <Tooltip
                formatter={(value, name) => [formatCurrency(Number(value ?? 0)), humanizeSeriesName(String(name ?? ''))]}
                labelFormatter={(label) => formatShortDate(label)}
                contentStyle={chartTooltipStyle}
              />
              <Legend />
              <Line type="monotone" dataKey="strategy_equity" name="strategy_equity" stroke="#06b6d4" strokeWidth={2.25} dot={false} />
              <Line type="monotone" dataKey="benchmark_equity" name="benchmark_equity" stroke="#a855f7" strokeWidth={2.25} dot={false} />
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
                <Line type="monotone" dataKey="strategy_drawdown_pct" name="strategy_drawdown_pct" stroke="#e11d48" strokeWidth={2.25} dot={false} />
                <Line type="monotone" dataKey="benchmark_drawdown_pct" name="benchmark_drawdown_pct" stroke="#f59e0b" strokeWidth={2.25} dot={false} />
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

function ChartFrame({ children }: { children: React.ReactNode }) {
  return <div className="h-[340px] w-full">{children}</div>;
}
