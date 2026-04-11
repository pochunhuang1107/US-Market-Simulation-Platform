interface StateCardProps {
  title: string;
  description?: string;
  tone?: 'default' | 'error';
}

export function StateCard({ title, description, tone = 'default' }: StateCardProps) {
  const toneClass =
    tone === 'error'
      ? 'border-rose-300/50 bg-rose-50/90 text-rose-900 dark:border-rose-900/70 dark:bg-rose-950/20 dark:text-rose-100'
      : 'app-card text-[var(--text)]';

  return (
    <div className={`rounded-3xl border p-8 app-shadow-soft ${toneClass}`}>
      <h3 className="text-lg font-semibold">{title}</h3>
      {description ? <p className="mt-2 text-sm app-text-muted">{description}</p> : null}
    </div>
  );
}
