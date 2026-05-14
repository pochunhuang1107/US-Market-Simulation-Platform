import type { ModelSignalCatalogItemResponse, RunResponse } from '../types/api';

export type ModelSignalRunContext = {
  displayName: string | null;
  modelVersion: string | null;
  rankingField: string | null;
  topN: number | null;
  signalBucketFilter: string[];
  fallback: string | null;
  latestSignalDate: string | null;
  researchStatus: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function cleanString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function cleanNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function cleanStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

export function getDraftConfigFromRun(run: RunResponse): Record<string, unknown> | null {
  const draftConfig = run.request_payload?.draft_config;

  if (isRecord(draftConfig)) {
    return draftConfig;
  }

  return null;
}

function getModelSignalConfig(run: RunResponse): Record<string, unknown> | null {
  const draftConfig = getDraftConfigFromRun(run);
  if (isRecord(draftConfig?.model_signal) && draftConfig.model_signal.enabled === true) {
    return draftConfig.model_signal;
  }

  const summary = run.summary_json ?? {};
  if (summary.strategy_type === 'model_signal') {
    return {};
  }

  return null;
}

function formatFallback(value: unknown): string | null {
  if (!isRecord(value)) return null;

  const type = cleanString(value.type);
  const symbol = cleanString(value.symbol);
  if (!type) return null;

  return type === 'asset' && symbol ? symbol.toUpperCase() : type;
}

function formatResearchStatus(value: string | null): string {
  if (!value) return 'Research / paper tracking';

  const normalized = value.replace(/_/g, ' ').trim().toLowerCase();
  if (!normalized) return 'Research / paper tracking';
  if (normalized.includes('paper tracking')) return 'Paper tracking';
  if (normalized === 'research only' || normalized === 'research-only') return 'Research / paper tracking';

  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function isModelSignalRun(run: RunResponse): boolean {
  return getModelSignalConfig(run) !== null;
}

export function getModelSignalVersion(run: RunResponse): string | null {
  const config = getModelSignalConfig(run);
  const summary = run.summary_json ?? {};

  return cleanString(config?.model_version) ?? cleanString(summary.model_signal_model_version);
}

export function buildModelSignalRunContext(
  run: RunResponse,
  catalogModel?: ModelSignalCatalogItemResponse | null
): ModelSignalRunContext | null {
  const config = getModelSignalConfig(run);
  if (!config) return null;

  const draftConfig = getDraftConfigFromRun(run);
  const summary = run.summary_json ?? {};

  return {
    displayName: catalogModel?.display_name ?? cleanString(draftConfig?.name),
    modelVersion: getModelSignalVersion(run),
    rankingField: cleanString(config.ranking_field) ?? cleanString(summary.model_signal_ranking_field),
    topN: cleanNumber(config.top_n) ?? cleanNumber(summary.model_signal_top_n),
    signalBucketFilter: cleanStringArray(config.signal_bucket_filter),
    fallback: formatFallback(config.fallback),
    latestSignalDate: cleanString(run.request_payload?.latest_signal_date) ?? cleanString(draftConfig?.end_date),
    researchStatus: formatResearchStatus(catalogModel?.research_status ?? null)
  };
}

export function formatModelSignalList(values: string[], emptyLabel = 'All buckets'): string {
  return values.length > 0 ? values.join(', ') : emptyLabel;
}
