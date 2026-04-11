const STATUS_STYLES: Record<string, string> = {
  SUCCEEDED: 'app-chip-success',
  SUCCESS: 'app-chip-success',
  RUNNING: 'app-chip-info',
  LEASED: 'app-chip-info',
  PENDING: 'app-chip-warning',
  FAILED: 'app-alert-error',
  CANCELED: 'app-pill app-text-muted',
  CANCELLED: 'app-pill app-text-muted'
};

export function RunStatusBadge({ status }: { status: string }) {
  const classes = STATUS_STYLES[status.toUpperCase()] ?? 'app-pill app-text-muted';

  return (
    <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${classes}`}>
      {status.replaceAll('_', ' ')}
    </span>
  );
}
