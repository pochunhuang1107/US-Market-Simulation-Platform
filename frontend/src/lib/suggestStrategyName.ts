const GENERIC_NAME_PATTERNS = new Set([
  'chat strategy',
  'draft strategy',
  'my strategy',
  'simple strategy',
  'untitled strategy'
]);

const ACRONYMS = new Set([
  'ETF',
  'GLD',
  'KD',
  'MACD',
  'QQQ',
  'RSI',
  'SMA',
  'SPY',
  'TLT',
  'VIX'
]);

type DraftRule = Record<string, unknown>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function getString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function normalizeName(value: string): string {
  return value
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ');
}

function isGenericName(value: string): boolean {
  const normalized = normalizeName(value).toLowerCase();
  if (GENERIC_NAME_PATTERNS.has(normalized)) return true;

  const withoutLeadingSymbol = normalized.replace(/^[a-z]{2,5}\s+/, '');
  return GENERIC_NAME_PATTERNS.has(withoutLeadingSymbol);
}

function cleanMeaningfulName(value: string): string | null {
  const normalized = normalizeName(value);
  if (!normalized || isGenericName(normalized)) return null;

  return normalized
    .split(' ')
    .map((word) => {
      const upper = word.toUpperCase();
      if (ACRONYMS.has(upper)) return upper;
      if (/^[A-Z]{2,5}$/.test(word)) return word;
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(' ');
}

function getRuleType(rule: unknown): string | null {
  return isRecord(rule) ? getString(rule.type) : null;
}

function getRuleSymbol(rule: unknown): string | null {
  return isRecord(rule) ? getString(rule.symbol) : null;
}

function getReferenceSymbol(rule: unknown): string | null {
  return isRecord(rule) ? getString(rule.reference_symbol) : null;
}

function collectAtomicRules(rule: unknown): DraftRule[] {
  if (!isRecord(rule)) return [];

  if (rule.kind === 'atomic' || typeof rule.type === 'string') {
    return [rule];
  }

  if (isRecord(rule.rule)) {
    return collectAtomicRules(rule.rule);
  }

  const nestedRules = [rule.rules, rule.conditions, rule.steps].find(Array.isArray);
  if (Array.isArray(nestedRules)) {
    return nestedRules.flatMap(collectAtomicRules);
  }

  return [];
}

function hasRuleType(rules: DraftRule[], types: Set<string>): boolean {
  return rules.some((rule) => {
    const type = getRuleType(rule);
    return type !== null && types.has(type);
  });
}

function findRuleByType(rules: DraftRule[], types: Set<string>): DraftRule | null {
  return rules.find((rule) => {
    const type = getRuleType(rule);
    return type !== null && types.has(type);
  }) ?? null;
}

function getSymbol(config: Record<string, unknown>, rules: DraftRule[]): string | null {
  const symbol = getString(config.tradable_symbol) ?? rules.map(getRuleSymbol).find(Boolean) ?? null;
  return symbol?.toUpperCase() ?? null;
}

function hasCoreOverlay(config: Record<string, unknown>): boolean {
  return isRecord(config.core_overlay) && config.core_overlay.enabled === true;
}

function getRuleTheme(entryRules: DraftRule[], exitRules: DraftRule[]): string | null {
  const allRules = [...entryRules, ...exitRules];

  if (hasRuleType(allRules, new Set(['relative_return_above', 'relative_strength_above', 'relative_strength_below']))) {
    return 'relative_strength';
  }

  if (hasRuleType(allRules, new Set(['realized_volatility_below', 'realized_volatility_above']))) {
    return 'realized_volatility';
  }

  if (hasRuleType(allRules, new Set([
    'bullish_candle',
    'bearish_candle',
    'close_above_previous_high',
    'close_below_previous_low',
    'close_near_high',
    'close_near_low'
  ]))) {
    return 'daily_price_action';
  }

  if (hasRuleType(entryRules, new Set(['rsi_below'])) && hasRuleType(exitRules, new Set(['rsi_above']))) {
    return 'rsi_mean_reversion';
  }

  if (hasRuleType(allRules, new Set(['rsi_below', 'rsi_above']))) {
    return 'rsi';
  }

  if (hasRuleType(entryRules, new Set(['sma_cross_above'])) && hasRuleType(exitRules, new Set(['sma_cross_below']))) {
    return 'sma_crossover';
  }

  if (hasRuleType(allRules, new Set(['sma_cross_above', 'sma_cross_below', 'sma_above']))) {
    return 'sma';
  }

  if (hasRuleType(allRules, new Set(['month_in']))) {
    return 'seasonality';
  }

  if (hasRuleType(allRules, new Set(['macd_bullish_cross', 'macd_bearish_cross']))) {
    return 'macd';
  }

  if (hasRuleType(allRules, new Set(['kd_golden_cross', 'kd_dead_cross']))) {
    return 'kd';
  }

  return null;
}

function getReferenceTrendFilterSymbol(entryRules: DraftRule[], tradableSymbol: string): string | null {
  const trendRule = entryRules.find((rule) => {
    const type = getRuleType(rule);
    const ruleSymbol = getRuleSymbol(rule)?.toUpperCase();
    return (
      type === 'sma_above' &&
      rule.fast_window === 1 &&
      ruleSymbol !== null &&
      ruleSymbol !== tradableSymbol
    );
  });

  return getRuleSymbol(trendRule)?.toUpperCase() ?? null;
}

function buildNameFromRules(config: Record<string, unknown>): string | null {
  const entryRules = collectAtomicRules(config.entry_rule);
  const exitRules = collectAtomicRules(config.exit_rule);
  const allRules = [...entryRules, ...exitRules];
  const symbol = getSymbol(config, allRules);
  if (!symbol) return null;

  const referenceTrendFilterSymbol = getReferenceTrendFilterSymbol(entryRules, symbol);
  if (
    referenceTrendFilterSymbol &&
    hasRuleType(entryRules, new Set(['rsi_below'])) &&
    hasRuleType(exitRules, new Set(['rsi_above']))
  ) {
    return `${symbol} RSI with ${referenceTrendFilterSymbol} trend filter`;
  }

  const theme = getRuleTheme(entryRules, exitRules);
  if (!theme) return null;

  const coreOverlay = hasCoreOverlay(config);

  if (theme === 'relative_strength') {
    const relativeRule = findRuleByType(allRules, new Set(['relative_return_above', 'relative_strength_above', 'relative_strength_below']));
    const referenceSymbol = getReferenceSymbol(relativeRule)?.toUpperCase() ?? getString(config.benchmark_symbol)?.toUpperCase();
    return referenceSymbol ? `${symbol} relative strength vs ${referenceSymbol}` : `${symbol} relative strength strategy`;
  }

  if (coreOverlay) {
    const strategyLabel = theme === 'rsi_mean_reversion' ? 'RSI' : themeLabel(theme);
    return `${symbol} core-overlay ${strategyLabel} strategy`;
  }

  if (theme === 'rsi_mean_reversion') return `${symbol} RSI mean reversion`;
  if (theme === 'sma_crossover') return `${symbol} SMA crossover`;
  if (theme === 'seasonality') return `${symbol} seasonality strategy`;
  if (theme === 'realized_volatility') return `${symbol} realized volatility strategy`;
  if (theme === 'daily_price_action') return `${symbol} daily price-action strategy`;

  return `${symbol} ${themeLabel(theme)} strategy`;
}

function themeLabel(theme: string): string {
  switch (theme) {
    case 'rsi':
    case 'rsi_mean_reversion':
      return 'RSI';
    case 'sma':
    case 'sma_crossover':
      return 'SMA';
    case 'macd':
      return 'MACD';
    case 'kd':
      return 'KD';
    case 'seasonality':
      return 'seasonality';
    case 'realized_volatility':
      return 'realized volatility';
    case 'daily_price_action':
      return 'daily price-action';
    default:
      return 'strategy';
  }
}

export function suggestStrategyNameFromConfig(config: unknown): string {
  if (!isRecord(config)) return 'My strategy';

  const ruleName = buildNameFromRules(config);
  if (ruleName) return ruleName;

  const configName = getString(config.name);
  const cleanedName = configName ? cleanMeaningfulName(configName) : null;
  return cleanedName ?? 'My strategy';
}
