interface StateCardProps {
  title: string;
  description?: string;
  tone?: 'default' | 'error';
}

export function StateCard({ title, description, tone = 'default' }: StateCardProps) {
  const toneClass = tone === 'error' ? 'border-rose-900/70 bg-rose-950/20 text-rose-100' : 'border-slate-800 bg-slate-900/70 text-slate-200';

  return (
    <div className={`rounded-3xl border p-8 shadow-2xl shadow-slate-950/30 ${toneClass}`}>
      <h3 className="text-lg font-semibold">{title}</h3>
      {description ? <p className="mt-2 text-sm text-slate-400">{description}</p> : null}
    </div>
  );
}
