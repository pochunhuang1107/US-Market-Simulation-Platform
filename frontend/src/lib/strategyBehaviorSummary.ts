export type StrategyBehaviorField = {
  label: string;
  value: string;
};

function getRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`;
}

export function getStrategyBehaviorFields(config: Record<string, unknown> | null | undefined): StrategyBehaviorField[] {
  if (!config) return [];

  const allocation = getRecord(config.allocation);
  const positionManagement = getRecord(config.position_management);
  const fields: StrategyBehaviorField[] = [];
  const scaleInFraction = positionManagement?.scale_in_fraction;

  if (typeof scaleInFraction === 'number') {
    fields.push({ label: 'Entry sizing', value: `${formatPercent(scaleInFraction)} per entry` });
  } else if (typeof allocation?.entry_value === 'number') {
    fields.push({ label: 'Entry allocation', value: `${formatPercent(allocation.entry_value)} of equity` });
  }

  if (typeof positionManagement?.max_scale_in_steps === 'number') {
    fields.push({ label: 'Max entries', value: String(positionManagement.max_scale_in_steps) });
  }

  const minBarsBetweenAdds = positionManagement?.min_bars_between_scale_ins;
  if (typeof minBarsBetweenAdds === 'number' && minBarsBetweenAdds > 0) {
    fields.push({ label: 'Wait between adds', value: `${minBarsBetweenAdds} bars` });
  }

  if (positionManagement?.scale_in_requires_persistent_signal === true) {
    fields.push({ label: 'Scale-in signal', value: 'Requires persistent signal' });
  }

  if (positionManagement?.exit_behavior === 'sell_all') {
    fields.push({ label: 'Exit behavior', value: 'Sell all' });
  } else if (positionManagement?.exit_behavior === 'scale_out' || typeof positionManagement?.scale_out_fraction === 'number') {
    const scaleOutFraction =
      typeof positionManagement?.scale_out_fraction === 'number' ? positionManagement.scale_out_fraction : 0.5;
    fields.push({ label: 'Exit behavior', value: `Scale out ${formatPercent(scaleOutFraction)} at a time` });
  }

  if (typeof allocation?.max_position_pct === 'number') {
    fields.push({ label: 'Max position', value: formatPercent(allocation.max_position_pct) });
  }

  if (typeof config.benchmark_symbol === 'string' && config.benchmark_symbol.trim()) {
    fields.push({ label: 'Benchmark', value: config.benchmark_symbol });
  }

  return fields;
}
