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
  'allocation.max_position_pct': 'Max position'
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
  'allocation.max_position_pct': 'Max position'
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
  'core_overlay.'
];

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

export function formatParameterLabel(path: string): string {
  return PARAMETER_LABELS[path] ?? path;
}

export function formatCompactParameterLabel(path: string): string {
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

export function formatParameterSummary(value: unknown): string {
  const entries = sortedParameterEntries(value);
  if (entries.length === 0) return 'No parameter changes';
  if (entries.length > 2) return `${entries.length} parameter changes`;

  return entries
    .map(([path, parameterValue]) => `${formatCompactParameterLabel(path)} ${formatParameterValue(parameterValue)}`)
    .join(' · ');
}
