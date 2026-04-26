interface MetricCardProps {
  label: string;
  value: string;
  tone?: 'default' | 'positive' | 'negative';
}

export function MetricCard({ label, value, tone = 'default' }: MetricCardProps) {
  const toneClass =
    tone === 'positive'
      ? 'text-emerald-500 dark:text-emerald-300'
      : tone === 'negative'
        ? 'text-rose-500 dark:text-rose-300'
        : 'app-title';

  return (
    <div className="app-card-soft grid min-h-28 content-between gap-3 rounded-2xl border p-4">
      <p className="min-h-8 text-xs font-semibold uppercase tracking-[0.18em] app-text-soft">{label}</p>
      <p className={`text-2xl font-semibold ${toneClass}`}>{value}</p>
    </div>
  );
}
