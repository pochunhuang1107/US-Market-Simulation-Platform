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

type RunSourceMetadata = {
  source?: Nullable<string>;
  source_sweep_run_id?: Nullable<string>;
  source_variant_id?: Nullable<string>;
  source_variant_rank?: Nullable<number>;
  source_ranking_metric?: Nullable<string>;
};

export function isSavedSweepVariantResult(run: RunSourceMetadata): boolean {
  return run.source === 'sweep_variant_save';
}

export function formatSavedSweepVariantSource(run: RunSourceMetadata): string {
  const sweepId = shortRunId(run.source_sweep_run_id);
  const variantId = shortRunId(run.source_variant_id);
  const parts = [];

  if (sweepId) parts.push(`sweep ${sweepId}`);
  if (variantId) parts.push(`variant ${variantId}`);

  return parts.length > 0 ? `Saved from ${parts.join(' · ')}` : 'Saved from sweep variant';
}

const RUN_TYPE_LABELS: Record<string, string> = {
  SIMULATION: 'Simulation result',
  PORTFOLIO: 'Portfolio result',
  COMPARISON: 'Comparison result',
  PARAMETER_SWEEP: 'Parameter sweep result'
};

const EXECUTOR_TYPE_LABELS: Record<string, string> = {
  SIMULATION_EXECUTOR: 'Simulation engine',
  PORTFOLIO_EXECUTOR: 'Portfolio engine',
  COMPARISON_EXECUTOR: 'Comparison engine',
  SWEEP_EXECUTOR: 'Sweep engine'
};

const STRATEGY_TYPE_LABELS: Record<string, string> = {
  SINGLE_ASSET: 'Single ETF',
  SIMULATION: 'Single ETF'
};

const STRATEGY_STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Active',
  ARCHIVED: 'Archived'
};

function titleCaseRawValue(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function formatRunType(value: string): string {
  return RUN_TYPE_LABELS[value] ?? titleCaseRawValue(value);
}

export function formatExecutorType(value: string): string {
  return EXECUTOR_TYPE_LABELS[value] ?? titleCaseRawValue(value);
}

export function formatStrategyType(value: string): string {
  return STRATEGY_TYPE_LABELS[value] ?? titleCaseRawValue(value);
}

export function formatStrategyStatus(value: string): string {
  return STRATEGY_STATUS_LABELS[value] ?? titleCaseRawValue(value);
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
    return shortId ? `Result · v${versionNumber} · ${shortId}` : `Result · v${versionNumber}`;
  }

  return shortId ? `Draft result · ${shortId}` : 'Draft result';
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
