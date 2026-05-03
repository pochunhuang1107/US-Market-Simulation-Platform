const PARAMETER_LABELS: Record<string, string> = {
  'entry_rule.slow_window': 'Entry slow window',
  'exit_rule.slow_window': 'Exit slow window',
  'entry_rule.fast_window': 'Entry fast window',
  'exit_rule.fast_window': 'Exit fast window',
  'entry_rule.threshold': 'Entry threshold',
  'exit_rule.threshold': 'Exit threshold',
  'entry_rule.lookback': 'Entry lookback',
  'exit_rule.lookback': 'Exit lookback',
  'risk.stop_loss_pct': 'Stop loss',
  'risk.take_profit_pct': 'Take profit',
  'risk.cooldown_bars': 'Cooldown bars',
  'allocation.entry_value': 'Entry allocation',
  'allocation.max_position_pct': 'Max position',
  'core_overlay.core_allocation_pct': 'Core allocation',
  'position_management.scale_in_fraction': 'Scale in',
  'position_management.scale_out_fraction': 'Scale out'
};

const COMPACT_PARAMETER_LABELS: Record<string, string> = {
  'entry_rule.slow_window': 'Entry slow',
  'exit_rule.slow_window': 'Exit slow',
  'entry_rule.fast_window': 'Entry fast',
  'exit_rule.fast_window': 'Exit fast',
  'entry_rule.threshold': 'Entry threshold',
  'exit_rule.threshold': 'Exit threshold',
  'entry_rule.lookback': 'Entry lookback',
  'exit_rule.lookback': 'Exit lookback',
  'risk.stop_loss_pct': 'Stop loss',
  'risk.take_profit_pct': 'Take profit',
  'risk.cooldown_bars': 'Cooldown',
  'allocation.entry_value': 'Entry allocation',
  'allocation.max_position_pct': 'Max position',
  'core_overlay.core_allocation_pct': 'Core allocation',
  'position_management.scale_in_fraction': 'Scale in',
  'position_management.scale_out_fraction': 'Scale out'
};

const RANKING_LABELS: Record<string, string> = {
  total_return_pct: 'Total Return',
  benchmark_return_pct: 'Benchmark Return',
  alpha_vs_benchmark_pct: 'Alpha',
  cagr_pct: 'CAGR',
  sharpe_ratio: 'Sharpe',
  max_drawdown_pct: 'Max Drawdown',
  trade_count: 'Trades'
};

const PARAMETER_GROUP_ORDER = [
  'entry_rule.',
  'exit_rule.',
  'risk.',
  'allocation.',
  'core_overlay.',
  'position_management.'
];

type PathPart = {
  key: string;
  index: number | null;
};

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function toStringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

export function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function formatRankingMetricName(value: unknown): string {
  const raw = toStringValue(value);
  if (!raw) return 'Ranking metric';
  return RANKING_LABELS[raw] ?? raw.replace(/_/g, ' ');
}

export function formatTopVariantLabel(value: unknown): string {
  const metric = formatRankingMetricName(value);
  return metric === 'Ranking metric' ? 'Rank #1' : `Top by ${metric}`;
}

export function formatParameterValue(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

function parsePathPart(part: string): PathPart {
  const match = part.match(/^(.+)\[(\d+)\]$/);
  if (!match) return { key: part, index: null };
  return { key: match[1], index: Number(match[2]) };
}

function getNestedValue(config: unknown, path: string): unknown {
  let current: unknown = config;
  for (const part of path.split('.')) {
    if (!isRecord(current)) return null;
    const { key, index } = parsePathPart(part);
    current = current[key];
    if (index !== null) {
      if (!Array.isArray(current)) return null;
      current = current[index];
    }
  }
  return current;
}

function sideLabelForPath(path: string): 'Entry' | 'Exit' | null {
  if (path.startsWith('entry_rule.')) return 'Entry';
  if (path.startsWith('exit_rule.')) return 'Exit';
  return null;
}

function thresholdLabelForRule(path: string, config?: unknown): string | null {
  if (!path.endsWith('.threshold')) return null;
  if (!config) return null;

  const rule = getNestedValue(config, path.replace(/\.threshold$/, ''));
  if (!isRecord(rule)) return null;

  const type = toStringValue(rule.type);
  const side = sideLabelForPath(path);

  if (type === 'rsi_below' || type === 'rsi_above') {
    return side ? `${side} RSI threshold` : 'RSI threshold';
  }

  if (type === 'series_below' || type === 'series_above') {
    const symbol = toStringValue(rule.symbol)?.toUpperCase() ?? 'Series';
    if (symbol === 'VIX' && path.startsWith('entry_rule.')) return 'VIX add threshold';
    if (symbol === 'VIX' && path.startsWith('exit_rule.')) return 'VIX reduce threshold';
    return side ? `${side} ${symbol} threshold` : `${symbol} threshold`;
  }

  return null;
}

function numberFormatter(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

function plural(value: number, singular: string, pluralValue = `${singular}s`): string {
  return value === 1 ? singular : pluralValue;
}

export function formatTradeActivity(summary: unknown): string {
  if (!isRecord(summary)) return '—';

  const tradeCount = toNumber(summary.trade_count);
  const fullExitCount = toNumber(summary.full_exit_count) ?? tradeCount;
  const eventCount = toNumber(summary.trade_event_count);
  const addEventCount = toNumber(summary.add_event_count) ?? 0;
  const reduceEventCount = toNumber(summary.reduce_event_count) ?? 0;

  if (
    eventCount !== null &&
    fullExitCount !== null &&
    eventCount !== fullExitCount &&
    (addEventCount > 0 || reduceEventCount > 0)
  ) {
    return `${numberFormatter(fullExitCount)} ${plural(fullExitCount, 'exit')} · ${numberFormatter(
      eventCount
    )} ${plural(eventCount, 'event')}`;
  }

  if (tradeCount === null) return '—';
  return `${numberFormatter(tradeCount)} ${plural(tradeCount, 'trade')}`;
}

export function formatParameterLabel(path: string, config?: unknown): string {
  const contextualLabel = thresholdLabelForRule(path, config);
  if (contextualLabel) return contextualLabel;
  return PARAMETER_LABELS[path] ?? path;
}

export function formatCompactParameterLabel(path: string, config?: unknown): string {
  const contextualLabel = thresholdLabelForRule(path, config);
  if (contextualLabel) return contextualLabel;
  return COMPACT_PARAMETER_LABELS[path] ?? PARAMETER_LABELS[path] ?? path;
}

export function parameterEntries(value: unknown): [string, unknown][] {
  if (!isRecord(value)) return [];
  return Object.entries(value);
}

function parameterSortKey(path: string): [number, string] {
  const groupIndex = PARAMETER_GROUP_ORDER.findIndex((prefix) => path.startsWith(prefix));
  return [groupIndex === -1 ? PARAMETER_GROUP_ORDER.length : groupIndex, path];
}

export function sortedParameterEntries(value: unknown): [string, unknown][] {
  return parameterEntries(value).sort(([leftPath], [rightPath]) => {
    const [leftGroup, leftKey] = parameterSortKey(leftPath);
    const [rightGroup, rightKey] = parameterSortKey(rightPath);
    if (leftGroup !== rightGroup) return leftGroup - rightGroup;
    return leftKey.localeCompare(rightKey);
  });
}

export function formatParameterSummary(value: unknown, config?: unknown): string {
  const entries = sortedParameterEntries(value);
  if (entries.length === 0) return 'No parameter changes';
  if (entries.length > 2) return `${entries.length} parameter changes`;

  return entries
    .map(
      ([path, parameterValue]) =>
        `${formatCompactParameterLabel(path, config)} ${formatParameterValue(parameterValue)}`
    )
    .join(' · ');
}
