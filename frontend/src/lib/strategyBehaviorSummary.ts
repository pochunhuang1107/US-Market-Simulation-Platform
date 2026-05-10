export type StrategyBehaviorField = {
  label: string;
  value: string;
};

export const MINIMUM_TRADE_SELF_BLOCKING_WARNING =
  'Minimum trade size may block entries because entry size is at or below the minimum trade threshold. Whole-share rounding can make trades smaller than the minimum.';

function getRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function getNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function getString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`;
}

function formatCurrency(value: number): string {
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

export function getStrategyBehaviorFields(config: Record<string, unknown> | null | undefined): StrategyBehaviorField[] {
  if (!config) return [];

  const allocation = getRecord(config.allocation);
  const coreOverlay = getRecord(config.core_overlay);
  const positionManagement = getRecord(config.position_management);
  const rotation = getRecord(config.rotation);
  const fields: StrategyBehaviorField[] = [];

  if (rotation?.enabled === true) {
    const ranking = getRecord(rotation.ranking);
    const rebalance = getRecord(rotation.rebalance);
    const selection = getRecord(rotation.selection);
    const rotationAllocation = getRecord(rotation.allocation);
    const fallback = getRecord(rotation.fallback);
    const universe = Array.isArray(rotation.universe)
      ? rotation.universe.filter((symbol): symbol is string => typeof symbol === 'string' && symbol.trim().length > 0)
      : [];
    const frequency = getString(rebalance?.frequency);
    const lookback = getNumber(ranking?.lookback);
    const topN = getNumber(selection?.top_n);
    const maxPositionPct = getNumber(rotationAllocation?.max_position_pct);
    const fallbackType = getString(fallback?.type);
    const fallbackSymbol = getString(fallback?.symbol);

    if (universe.length > 0) {
      fields.push({ label: 'Rotation universe', value: universe.join(', ') });
    }
    if (lookback !== null) {
      fields.push({ label: 'Momentum lookback', value: `${lookback} trading days` });
    }
    if (frequency) {
      fields.push({ label: 'Rebalance', value: frequency });
    }
    if (topN !== null) {
      fields.push({ label: 'Selection', value: `Top ${topN}` });
    }
    if (maxPositionPct !== null) {
      fields.push({ label: 'Rotation max position', value: formatPercent(maxPositionPct) });
    }
    if (fallbackType) {
      fields.push({
        label: 'Fallback',
        value: fallbackType === 'asset' && fallbackSymbol ? fallbackSymbol.toUpperCase() : fallbackType
      });
    }
    if (typeof config.benchmark_symbol === 'string' && config.benchmark_symbol.trim()) {
      fields.push({ label: 'Benchmark', value: config.benchmark_symbol });
    }

    return fields;
  }

  const scaleInFraction = positionManagement?.scale_in_fraction;
  const coreAllocationPct =
    coreOverlay?.enabled === true && typeof coreOverlay.core_allocation_pct === 'number'
      ? coreOverlay.core_allocation_pct
      : null;
  const hasCoreOverlay = coreAllocationPct !== null && coreAllocationPct > 0;

  if (typeof scaleInFraction === 'number') {
    fields.push({
      label: 'Entry sizing',
      value: hasCoreOverlay
        ? `${formatPercent(scaleInFraction)} of tactical sleeve per entry`
        : `${formatPercent(scaleInFraction)} per entry`
    });
  } else if (typeof allocation?.entry_value === 'number') {
    fields.push({
      label: 'Entry allocation',
      value: hasCoreOverlay
        ? `${formatPercent(allocation.entry_value)} of tactical sleeve`
        : `${formatPercent(allocation.entry_value)} of equity`
    });
  }

  if (hasCoreOverlay) {
    fields.push({ label: 'Core allocation', value: formatPercent(coreAllocationPct) });
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
    fields.push({
      label: hasCoreOverlay ? 'Max overlay position' : 'Max position',
      value: hasCoreOverlay
        ? `${formatPercent(allocation.max_position_pct)} of tactical sleeve`
        : formatPercent(allocation.max_position_pct)
    });
  }

  if (typeof positionManagement?.minimum_trade_notional === 'number') {
    fields.push({ label: 'Minimum trade', value: formatCurrency(positionManagement.minimum_trade_notional) });
  }

  if (typeof positionManagement?.minimum_trade_pct_of_equity === 'number') {
    fields.push({ label: 'Minimum trade', value: `${formatPercent(positionManagement.minimum_trade_pct_of_equity)} of equity` });
  }

  if (typeof positionManagement?.minimum_trade_shares === 'number') {
    fields.push({ label: 'Minimum shares', value: String(positionManagement.minimum_trade_shares) });
  }

  if (typeof config.benchmark_symbol === 'string' && config.benchmark_symbol.trim()) {
    fields.push({ label: 'Benchmark', value: config.benchmark_symbol });
  }

  return fields;
}

export function getStrategyBehaviorWarnings(config: Record<string, unknown> | null | undefined): string[] {
  if (!config) return [];

  const allocation = getRecord(config.allocation);
  const positionManagement = getRecord(config.position_management);
  const minimumTradePct = getNumber(positionManagement?.minimum_trade_pct_of_equity);
  if (!allocation || !positionManagement || minimumTradePct === null) return [];

  const entryCandidates = [
    getNumber(allocation.entry_value),
    getNumber(positionManagement.scale_in_fraction)
  ];
  const hasSelfBlockingRisk = entryCandidates.some((entryValue) => entryValue !== null && entryValue <= minimumTradePct);

  return hasSelfBlockingRisk ? [MINIMUM_TRADE_SELF_BLOCKING_WARNING] : [];
}
