import type { Nullable } from '../types/api';

export function formatDateTime(value: Nullable<string>): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-CA', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value));
}

export function formatShortDate(value: string): string {
  return new Intl.DateTimeFormat('en-CA', {
    month: 'short',
    day: '2-digit',
    year: '2-digit'
  }).format(new Date(value));
}

export function formatMonthLabel(value: string): string {
  const date = new Date(`${value}-01T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-CA', {
    month: 'short',
    year: 'numeric'
  }).format(date);
}

export function formatCurrency(value: Nullable<number>): string {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0
  }).format(value);
}

export function formatPct(value: Nullable<number>): string {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(2)}%`;
}

export function formatDecimal(value: Nullable<number>, digits = 2): string {
  if (value === null || value === undefined) return '—';
  return value.toFixed(digits);
}

export function formatNumber(value: Nullable<number>): string {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-US').format(value);
}

export function shortRunId(runId: Nullable<string> | undefined): string {
  return runId ? runId.slice(0, 8) : '';
}

export function formatRunLabel(
  strategyName: Nullable<string>,
  versionNumber: Nullable<number>,
  runId?: Nullable<string>
): string {
  const shortId = shortRunId(runId);
  const name = strategyName?.trim();

  if (name) {
    if (versionNumber === null || versionNumber === undefined) return name;
    return `${name} · v${versionNumber}`;
  }

  if (versionNumber !== null && versionNumber !== undefined) {
    return shortId ? `Run · v${versionNumber} · ${shortId}` : `Run · v${versionNumber}`;
  }

  return shortId ? `Draft run · ${shortId}` : 'Draft run';
}

export function humanizeSeriesName(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function statusTone(status: string): string {
  switch (status.toUpperCase()) {
    case 'SUCCEEDED':
      return 'text-emerald-300';
    case 'FAILED':
      return 'text-rose-300';
    case 'RUNNING':
    case 'LEASED':
      return 'app-accent';
    case 'QUEUED':
    case 'PENDING':
      return 'text-amber-300';
    case 'CANCELED':
      return 'app-text-muted';
    default:
      return 'app-text-muted';
  }
}
