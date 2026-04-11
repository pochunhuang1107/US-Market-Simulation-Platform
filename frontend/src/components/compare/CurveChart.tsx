import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { formatPct, formatShortDate } from '../../lib/formatters';
import type { RunComparisonCurve } from '../../types/api';
import { useTheme } from '../../theme';
import { SectionCard } from '../shared/SectionCard';

interface CurveChartProps {
  title: string;
  subtitle: string;
  curves: RunComparisonCurve[];
  yFormatter?: (value: number) => string;
  zeroLine?: boolean;
}

const STROKES = ['#38bdf8', '#c084fc', '#22c55e', '#f59e0b', '#fb7185', '#f97316'];

export function CurveChart({ title, subtitle, curves, yFormatter = defaultFormatter, zeroLine = false }: CurveChartProps) {
  const data = mergeCurves(curves);
  const { resolvedTheme } = useTheme();
  const gridColor = resolvedTheme === 'dark' ? '#1e293b' : '#cbd5e1';
  const axisColor = resolvedTheme === 'dark' ? '#94a3b8' : '#64748b';
  const tooltipStyle = {
    background: resolvedTheme === 'dark' ? '#020617' : '#ffffff',
    border: `1px solid ${resolvedTheme === 'dark' ? '#334155' : '#cbd5e1'}`,
    borderRadius: 16,
    color: resolvedTheme === 'dark' ? '#e2e8f0' : '#0f172a'
  };

  return (
    <SectionCard title={title} subtitle={subtitle}>
      <div className="h-[340px] w-full">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
            <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
            <XAxis dataKey="date" tickFormatter={formatShortDate} minTickGap={36} stroke={axisColor} />
            <YAxis tickFormatter={yFormatter} stroke={axisColor} width={88} />
            <Tooltip
              formatter={(value, name) => [yFormatter(Number(value ?? 0)), name]}
              labelFormatter={(label) => formatShortDate(label)}
              contentStyle={tooltipStyle}
            />
            <Legend />
            {zeroLine ? <ReferenceLine y={0} stroke={gridColor} /> : null}
            {curves.map((curve, index) => (
              <Line
                key={curve.run_id}
                type="monotone"
                dataKey={curve.label}
                name={curve.label}
                stroke={STROKES[index % STROKES.length]}
                strokeWidth={2.25}
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </SectionCard>
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

export function pctFormatter(value: number) {
  return formatPct(value);
}
