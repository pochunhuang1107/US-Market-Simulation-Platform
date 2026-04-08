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

import { formatCurrency, formatMonthLabel, formatPct, formatShortDate, humanizeSeriesName } from '../../lib/formatters';
import type { RunChartDataResponse } from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

export function RunCharts({ chartData }: { chartData: RunChartDataResponse }) {
  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="Equity Curve" subtitle="Strategy and benchmark equity extracted from timeline artifacts.">
          <ChartFrame>
            <ResponsiveContainer>
              <LineChart data={chartData.equity_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="#94a3b8" />
                <YAxis tickFormatter={formatCurrency} stroke="#94a3b8" width={96} />
                <Tooltip
                  formatter={(value, name) => [
                    formatPct(Number(value ?? 0)),
                    humanizeSeriesName(String(name ?? ''))
                  ]}
                  labelFormatter={(label) => formatShortDate(label)}
                  contentStyle={{ background: '#020617', border: '1px solid #334155', borderRadius: 16 }}
                />
                <Legend />
                <Line type="monotone" dataKey="strategy_equity" name="strategy_equity" stroke="#38bdf8" strokeWidth={2.25} dot={false} />
                <Line type="monotone" dataKey="benchmark_equity" name="benchmark_equity" stroke="#c084fc" strokeWidth={2.25} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>

        <SectionCard title="Drawdown Curve" subtitle="Strategy and benchmark drawdown series.">
          <ChartFrame>
            <ResponsiveContainer>
              <LineChart data={chartData.drawdown_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="#94a3b8" />
                <YAxis tickFormatter={formatPct} stroke="#94a3b8" width={80} />
                <Tooltip
                  formatter={(value, name) => [
                    formatPct(Number(value ?? 0)),
                    humanizeSeriesName(String(name ?? ''))
                  ]}
                  labelFormatter={(label) => formatShortDate(label)}
                  contentStyle={{ background: '#020617', border: '1px solid #334155', borderRadius: 16 }}
                />
                <Legend />
                <ReferenceLine y={0} stroke="#475569" />
                <Line type="monotone" dataKey="strategy_drawdown_pct" name="strategy_drawdown_pct" stroke="#fb7185" strokeWidth={2.25} dot={false} />
                <Line type="monotone" dataKey="benchmark_drawdown_pct" name="benchmark_drawdown_pct" stroke="#f59e0b" strokeWidth={2.25} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
        <SectionCard title="Monthly Returns" subtitle="Month-over-month strategy returns from report artifacts.">
          <ChartFrame>
            <ResponsiveContainer>
              <BarChart data={chartData.monthly_returns} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="month" tickFormatter={formatMonthLabel} minTickGap={24} stroke="#94a3b8" />
                <YAxis tickFormatter={formatPct} stroke="#94a3b8" width={80} />
                <Tooltip
                  formatter={(value) => [formatPct(Number(value ?? 0)), 'Return']}
                  labelFormatter={(label) => formatMonthLabel(label)}
                  contentStyle={{ background: '#020617', border: '1px solid #334155', borderRadius: 16 }}
                />
                <ReferenceLine y={0} stroke="#475569" />
                <Bar dataKey="return_pct" name="return_pct" fill="#38bdf8" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>

        <SectionCard title="Trade Markers" subtitle="Artifact-derived trade events aligned to run dates.">
          <div className="max-h-[380px] overflow-auto rounded-2xl border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-950/60 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3">Shares</th>
                  <th className="px-4 py-3">Price</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-950/40">
                {chartData.trade_markers.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-slate-500">
                      No trade markers were available for this run.
                    </td>
                  </tr>
                ) : (
                  chartData.trade_markers.map((trade, index) => (
                    <tr key={`${trade.date}-${trade.side}-${index}`}>
                      <td className="px-4 py-3 text-slate-300">{formatShortDate(trade.date)}</td>
                      <td className="px-4 py-3 font-medium text-white">{trade.side}</td>
                      <td className="px-4 py-3 text-slate-300">{trade.shares ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-300">{trade.price?.toFixed(2) ?? '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </SectionCard>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="Sleeve Equity" subtitle="Core and overlay sleeve equity over time.">
          <ChartFrame>
            <ResponsiveContainer>
              <LineChart data={chartData.sleeve_equity_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="#94a3b8" />
                <YAxis tickFormatter={formatCurrency} stroke="#94a3b8" width={96} />
                <Tooltip
                  formatter={(value, name) => [
                    formatCurrency(Number(value ?? 0)),
                    humanizeSeriesName(String(name ?? ''))
                  ]}
                  labelFormatter={(label) => formatShortDate(label)}
                  contentStyle={{ background: '#020617', border: '1px solid #334155', borderRadius: 16 }}
                />
                <Legend />
                <Line type="monotone" dataKey="core_equity" name="core_equity" stroke="#22c55e" strokeWidth={2.25} dot={false} />
                <Line type="monotone" dataKey="overlay_equity" name="overlay_equity" stroke="#f59e0b" strokeWidth={2.25} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>

        <SectionCard title="Sleeve Weights" subtitle="Core and overlay weights through the run.">
          <ChartFrame>
            <ResponsiveContainer>
              <LineChart data={chartData.sleeve_weight_curve} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke="#94a3b8" />
                <YAxis tickFormatter={formatPct} stroke="#94a3b8" width={80} />
                <Tooltip
                  formatter={(value, name) => [
                    formatPct(Number(value ?? 0)),
                    humanizeSeriesName(String(name ?? ''))
                  ]}
                  labelFormatter={(label) => formatShortDate(label)}
                  contentStyle={{ background: '#020617', border: '1px solid #334155', borderRadius: 16 }}
                />
                <Legend />
                <Line type="monotone" dataKey="core_weight_pct" name="core_weight_pct" stroke="#4ade80" strokeWidth={2.25} dot={false} />
                <Line type="monotone" dataKey="overlay_weight_pct" name="overlay_weight_pct" stroke="#fbbf24" strokeWidth={2.25} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </SectionCard>
      </div>
    </div>
  );
}

function ChartFrame({ children }: { children: React.ReactNode }) {
  return <div className="h-[340px] w-full">{children}</div>;
}
