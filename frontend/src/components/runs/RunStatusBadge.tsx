interface RunStatusBadgeProps {
  status: string;
}

const STATUS_STYLES: Record<string, string> = {
  SUCCEEDED: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  FAILED: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  RUNNING: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300',
  LEASED: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300',
  QUEUED: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  PENDING: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  CANCELED: 'border-slate-500/30 bg-slate-500/10 text-slate-300'
};

export function RunStatusBadge({ status }: RunStatusBadgeProps) {
  const classes = STATUS_STYLES[status.toUpperCase()] ?? 'border-slate-500/30 bg-slate-500/10 text-slate-300';

  return <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${classes}`}>{status}</span>;
}
