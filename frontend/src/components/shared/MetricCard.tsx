interface MetricCardProps {
  label: string;
  value: string;
  tone?: 'default' | 'positive' | 'negative';
}

export function MetricCard({ label, value, tone = 'default' }: MetricCardProps) {
  const toneClass =
    tone === 'positive'
      ? 'text-emerald-300'
      : tone === 'negative'
        ? 'text-rose-300'
        : 'text-white';

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className={`mt-3 text-2xl font-semibold ${toneClass}`}>{value}</p>
    </div>
  );
}
