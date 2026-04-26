interface StateCardProps {
  title: string;
  description?: string;
  tone?: 'default' | 'error';
}

export function StateCard({ title, description, tone = 'default' }: StateCardProps) {
  const toneClass =
    tone === 'error'
      ? 'app-alert-error'
      : 'app-card text-[var(--text)]';
  const descriptionClass = tone === 'error' ? 'text-[var(--text)]' : 'app-text-muted';

  return (
    <div className={`rounded-3xl border p-8 app-shadow-soft ${toneClass}`}>
      <h3 className="text-lg font-semibold app-title">{title}</h3>
      {description ? <p className={`mt-2 text-sm ${descriptionClass}`}>{description}</p> : null}
    </div>
  );
}
