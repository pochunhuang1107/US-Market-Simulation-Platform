import { memo, useMemo } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TooltipContentProps, TooltipValueType } from 'recharts';

import { formatPct, formatShortDate } from '../../lib/formatters';
import type { RunComparisonCurve } from '../../types/api';
import { useTheme } from '../../theme';
import { SectionCard } from '../shared/SectionCard';

interface CurveChartProps {
  title: string;
  subtitle: string;
  note?: string;
  curves: RunComparisonCurve[];
  yFormatter?: (value: number) => string;
  zeroLine?: boolean;
}

const STRATEGY_STROKES = ['#38bdf8', '#c084fc', '#22c55e', '#f59e0b', '#fb7185', '#f97316'];
const BENCHMARK_STROKES = ['#64748b', '#475569', '#94a3b8', '#334155'];
const PARAMETER_VALUE_PATTERN = /-?\d+(?:\.\d+)?%?/g;

export const CurveChart = memo(function CurveChart({ title, subtitle, note, curves, yFormatter = defaultFormatter, zeroLine = false }: CurveChartProps) {
  const data = useMemo(() => mergeCurves(curves), [curves]);
  const { resolvedTheme } = useTheme();
  const gridColor = resolvedTheme === 'dark' ? '#1e293b' : '#cbd5e1';
  const axisColor = resolvedTheme === 'dark' ? '#94a3b8' : '#64748b';
  const tooltipStyle = useMemo(
    () => ({
      backgroundColor: resolvedTheme === 'dark' ? '#020617' : '#ffffff',
      borderColor: resolvedTheme === 'dark' ? '#334155' : '#cbd5e1',
      color: resolvedTheme === 'dark' ? '#e2e8f0' : '#0f172a'
    }),
    [resolvedTheme]
  );
  let strategyStrokeIndex = 0;
  let benchmarkStrokeIndex = 0;

  return (
    <SectionCard title={title} subtitle={subtitle}>
      {note ? (
        <div className="app-badge mb-4 inline-flex rounded-full px-3 py-1.5 text-xs font-semibold">
          {note}
        </div>
      ) : null}
      <div className="h-[340px] w-full">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
            <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
            <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke={axisColor} />
            <YAxis tickFormatter={yFormatter} stroke={axisColor} width={88} />
            <Tooltip
              content={(props: TooltipContentProps<TooltipValueType, string | number>) => (
                <CurveTooltip
                  {...props}
                  style={tooltipStyle}
                  yFormatter={yFormatter}
                />
              )}
            />
            <Legend />
            {zeroLine ? <ReferenceLine y={0} stroke={gridColor} /> : null}
            {curves.map((curve) => {
              const isBenchmark = Boolean(curve.benchmark_label) || curve.label.startsWith('Benchmark:');
              const stroke = isBenchmark
                ? BENCHMARK_STROKES[benchmarkStrokeIndex++ % BENCHMARK_STROKES.length]
                : STRATEGY_STROKES[strategyStrokeIndex++ % STRATEGY_STROKES.length];

              return (
                <Line
                  key={`${curve.result_ref ?? curve.run_id}:${curve.label}`}
                  type="monotone"
                  dataKey={curve.label}
                  name={curve.label}
                  stroke={stroke}
                  strokeWidth={isBenchmark ? 1.75 : 2.35}
                  dot={false}
                  opacity={isBenchmark ? 0.72 : 1}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </SectionCard>
  );
});

function CurveTooltip({
  active,
  label,
  payload,
  style,
  yFormatter
}: TooltipContentProps<TooltipValueType, string | number> & {
  style: {
    backgroundColor: string;
    borderColor: string;
    color: string;
  };
  yFormatter: (value: number) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const rows = payload.filter((item) => item.value !== undefined && item.value !== null && item.name);
  if (rows.length === 0) return null;

  return (
    <div
      className="w-64 rounded-xl border p-3 text-xs shadow-xl"
      style={{
        backgroundColor: style.backgroundColor,
        borderColor: style.borderColor,
        color: style.color
      }}
    >
      <div className="mb-2 font-semibold">{formatShortDate(String(label ?? ''))}</div>
      <div className="grid gap-1.5">
        {rows.map((item) => {
          const rawValue = Array.isArray(item.value) ? item.value[0] : item.value;
          const value = Number(rawValue ?? 0);
          const color = item.color ?? item.stroke ?? '#64748b';
          const name = String(item.name ?? '');

          return (
            <div key={name} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="truncate" title={name}>
                  {getCurveTooltipLabel(name)}
                </span>
              </div>
              <div className="font-mono tabular-nums">
                {yFormatter(value)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function mergeCurves(curves: RunComparisonCurve[]) {
  const byDate = new Map<string, Record<string, number | string>>();

  curves.forEach((curve) => {
    curve.points.forEach((point) => {
      const row = byDate.get(point.date) ?? { date: point.date };
      row[curve.label] = point.value;
      byDate.set(point.date, row);
    });
  });

  return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function defaultFormatter(value: number) {
  return value.toFixed(2);
}

export function getCurveTooltipLabel(label: string): string {
  const benchmarkLabel = label.match(/^Benchmark:\s*([^()]+)/i)?.[1]?.trim();
  if (benchmarkLabel) return `Benchmark: ${benchmarkLabel}`;

  const parts = label
    .split('·')
    .map((part) => part.trim())
    .filter(Boolean);
  const rankIndex = parts.findIndex((part) => /^Rank #\d+/i.test(part));
  if (rankIndex >= 0) {
    const rankLabel = parts[rankIndex];
    const parameterText = parts.slice(rankIndex + 1).join(' ');
    const parameterValues = parameterText.match(PARAMETER_VALUE_PATTERN)?.slice(0, 2) ?? [];
    return parameterValues.length > 0 ? `${rankLabel} · ${parameterValues.join('/')}` : rankLabel;
  }

  return label.replace(/\s+·\s+v(\d+)/i, ' v$1');
}

export function pctFormatter(value: number) {
  return formatPct(value);
}
