export type RuleRecord = Record<string, unknown>;

type RuleSummaryOptions = {
  tradableSymbol?: unknown;
  complexText?: string;
  reviewJsonForComplex?: boolean;
};

type RuleSummaryKind = 'empty' | 'simple' | 'complex' | 'custom';

export type RuleSummary = {
  text: string;
  kind: RuleSummaryKind;
};

function isRecord(value: unknown): value is RuleRecord {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function titleCase(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSymbol(value: unknown, fallback = 'Asset'): string {
  return typeof value === 'string' && value.trim() ? value.trim().toUpperCase() : fallback;
}

function formatThreshold(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'threshold';
  return Number.isInteger(value) ? String(value) : String(value);
}

function formatPercent(value: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'threshold';
  return `${(value * 100).toFixed(1)}%`;
}

function formatCompactPercent(value: number): string {
  return `${Number.isInteger(value * 100) ? value * 100 : (value * 100).toFixed(1)}%`;
}

function primarySymbol(rule: RuleRecord, options: RuleSummaryOptions): string {
  return formatSymbol(rule.symbol ?? options.tradableSymbol);
}

function relativeReturnAboveSummary(rule: RuleRecord, options: RuleSummaryOptions): string {
  const symbol = primarySymbol(rule, options);
  const referenceSymbol = formatSymbol(rule.reference_symbol, 'reference');
  const lookback = typeof rule.lookback === 'number' ? rule.lookback : 'the lookback';
  return `${symbol} outperforms ${referenceSymbol} by more than ${formatPercent(rule.threshold)} over ${lookback} trading days`;
}

function noLongerRelativeReturnAboveSummary(rule: RuleRecord, options: RuleSummaryOptions): string {
  const symbol = primarySymbol(rule, options);
  const referenceSymbol = formatSymbol(rule.reference_symbol, 'reference');
  const lookback = typeof rule.lookback === 'number' ? rule.lookback : 'the lookback';
  return `${symbol} no longer outperforms ${referenceSymbol} by more than ${formatPercent(rule.threshold)} over ${lookback} trading days`;
}

function realizedVolatilitySummary(rule: RuleRecord, options: RuleSummaryOptions, direction: 'below' | 'above'): string {
  const symbol = primarySymbol(rule, options);
  const lookback = typeof rule.lookback === 'number' ? rule.lookback : 'the lookback';
  return `${symbol} ${lookback}-day realized volatility is ${direction} ${formatPercent(rule.threshold)}`;
}

function summarizeAtomicRule(rule: RuleRecord, options: RuleSummaryOptions): string | null {
  const type = typeof rule.type === 'string' ? rule.type : 'unknown_rule';
  const symbol = primarySymbol(rule, options);
  const lookback = typeof rule.lookback === 'number' ? rule.lookback : null;
  const threshold = typeof rule.threshold === 'number' ? rule.threshold : null;
  const fastWindow = typeof rule.fast_window === 'number' ? rule.fast_window : 'fast';
  const slowWindow = typeof rule.slow_window === 'number' ? rule.slow_window : 'slow';
  const monthValues = Array.isArray(rule.month_values)
    ? rule.month_values.filter((value): value is number => typeof value === 'number')
    : [];

  switch (type) {
    case 'rsi_below':
      return `${symbol} RSI${lookback ? `(${lookback})` : ''} falls below ${threshold ?? 'threshold'}`;
    case 'rsi_above':
      return `${symbol} RSI${lookback ? `(${lookback})` : ''} rises above ${threshold ?? 'threshold'}`;
    case 'sma_cross_above':
      if (fastWindow === 1) return `${symbol} crosses above its ${slowWindow}-day SMA`;
      return `${symbol} ${fastWindow}-day SMA crosses above ${slowWindow}-day SMA`;
    case 'sma_cross_below':
      if (fastWindow === 1) return `${symbol} crosses below its ${slowWindow}-day SMA`;
      return `${symbol} ${fastWindow}-day SMA crosses below ${slowWindow}-day SMA`;
    case 'sma_above':
      if (fastWindow === 1) return `${symbol} is above its ${slowWindow}-day SMA`;
      return `${symbol} ${fastWindow}-day SMA stays above ${slowWindow}-day SMA`;
    case 'macd_bullish_cross':
      return `${symbol} MACD turns bullish`;
    case 'macd_bearish_cross':
      return `${symbol} MACD turns bearish`;
    case 'kd_golden_cross':
      return `${symbol} KD / stochastic turns bullish`;
    case 'kd_dead_cross':
      return `${symbol} KD / stochastic turns bearish`;
    case 'relative_return_above':
      return relativeReturnAboveSummary(rule, options);
    case 'realized_volatility_below':
      return realizedVolatilitySummary(rule, options, 'below');
    case 'realized_volatility_above':
      return realizedVolatilitySummary(rule, options, 'above');
    case 'bullish_candle':
      return `${symbol} closes above its open`;
    case 'bearish_candle':
      return `${symbol} closes below its open`;
    case 'close_above_previous_high':
      return `${symbol} closes above the previous day's high`;
    case 'close_below_previous_low':
      return `${symbol} closes below the previous day's low`;
    case 'close_near_high':
      return `${symbol} closes in the top ${formatCompactPercent(threshold ?? 0.2)} of the day's range`;
    case 'close_near_low':
      return `${symbol} closes in the bottom ${formatCompactPercent(threshold ?? 0.2)} of the day's range`;
    case 'relative_strength_above':
      return `${symbol} outperforms reference strength threshold${lookback ? ` over ${lookback} trading days` : ''}${threshold !== null ? ` by ${threshold}` : ''}`;
    case 'relative_strength_below':
      return `${symbol} underperforms reference strength threshold${lookback ? ` over ${lookback} trading days` : ''}${threshold !== null ? ` by ${threshold}` : ''}`;
    case 'month_in':
      return monthValues.length > 0
        ? `Only trade during months ${monthValues.join(', ')}`
        : 'Month filter is applied';
    default:
      return summarizeThresholdRule(rule, type);
  }
}

function summarizeThresholdRule(rule: RuleRecord, type: string): string | null {
  const value =
    typeof rule.threshold === 'number'
      ? rule.threshold
      : typeof rule.value === 'number'
        ? rule.value
        : null;

  if (value === null) return null;

  const operatorFromType = type.endsWith('_above')
    ? 'above'
    : type.endsWith('_below')
      ? 'below'
      : null;
  const operator =
    operatorFromType ??
    (typeof rule.operator === 'string' &&
    ['above', 'below'].includes(rule.operator.toLowerCase())
      ? rule.operator.toLowerCase()
      : null);

  if (!operator) return null;

  const rawSubject =
    typeof rule.symbol === 'string'
      ? rule.symbol
      : typeof rule.indicator === 'string'
        ? rule.indicator
        : type.startsWith('vix_')
          ? 'VIX'
          : '';
  const subject = formatSymbol(rawSubject, '');

  if (!subject) return null;

  return `${subject} ${operator} ${formatThreshold(value)}`;
}

export function summarizeRule(rule: unknown, options: RuleSummaryOptions = {}, depth = 0): RuleSummary {
  const complexText = options.complexText ?? 'Complex rule group';
  if (!isRecord(rule)) return { text: 'No rule defined', kind: 'empty' };

  const kind = typeof rule.kind === 'string' ? rule.kind : 'atomic';

  if (kind === 'atomic') {
    const atomicSummary = summarizeAtomicRule(rule, options);
    return {
      text: atomicSummary ?? titleCase(typeof rule.type === 'string' ? rule.type : 'Unknown rule'),
      kind: atomicSummary ? 'simple' : 'custom'
    };
  }

  if (kind === 'not') {
    const nestedRule = isRecord(rule.rule) ? rule.rule : null;
    if (
      nestedRule &&
      (nestedRule.kind === 'atomic' || nestedRule.kind === undefined) &&
      nestedRule.type === 'relative_return_above'
    ) {
      return { text: noLongerRelativeReturnAboveSummary(nestedRule, options), kind: 'simple' };
    }

    if (
      nestedRule &&
      (nestedRule.kind === 'atomic' || nestedRule.kind === undefined) &&
      nestedRule.type === 'sma_above' &&
      nestedRule.fast_window === 1
    ) {
      const symbol = primarySymbol(nestedRule, options);
      const slowWindow = typeof nestedRule.slow_window === 'number' ? nestedRule.slow_window : 'slow';
      return { text: `${symbol} price is no longer above its ${slowWindow}-day SMA`, kind: 'simple' };
    }

    if (options.reviewJsonForComplex) return { text: complexText, kind: 'complex' };
    const innerRule = nestedRule ? summarizeRule(nestedRule, options, depth + 1).text : 'the inner rule';
    return { text: `NOT: ${innerRule}`, kind: 'complex' };
  }

  if (kind === 'group' || rule.type === 'group') {
    const rules = Array.isArray(rule.rules) ? rule.rules : [];
    if (options.reviewJsonForComplex && (depth > 0 || rules.length > 3)) {
      return { text: complexText, kind: 'complex' };
    }

    const operator =
      typeof rule.operator === 'string' && ['AND', 'OR'].includes(rule.operator.toUpperCase())
        ? rule.operator.toUpperCase()
        : 'AND';
    const joiner = operator === 'OR' ? ' or ' : ' and ';
    const childSummaries = rules.map((child) => summarizeRule(child, options, depth + 1));

    if (
      options.reviewJsonForComplex &&
      (childSummaries.length === 0 || childSummaries.some((summary) => summary.kind !== 'simple'))
    ) {
      return { text: complexText, kind: 'complex' };
    }

    return childSummaries.length > 0
      ? { text: childSummaries.map((summary) => summary.text).join(joiner), kind: 'simple' }
      : { text: `${operator} group`, kind: 'simple' };
  }

  if (kind === 'window' || rule.type === 'window') {
    if (options.reviewJsonForComplex) return { text: complexText, kind: 'complex' };
    const windowBars = typeof rule.window_bars === 'number' ? rule.window_bars : null;
    const mode = typeof rule.mode === 'string' ? rule.mode : null;
    const innerRule = summarizeRule(rule.rule, options, depth + 1).text;

    if (windowBars && mode) return { text: `${titleCase(mode)} the following within ${windowBars} bars: ${innerRule}`, kind: 'complex' };
    if (windowBars) return { text: `Within ${windowBars} bars: ${innerRule}`, kind: 'complex' };
    return { text: `Window rule: ${innerRule}`, kind: 'complex' };
  }

  if (kind === 'sequence' || rule.type === 'sequence') {
    if (options.reviewJsonForComplex) return { text: complexText, kind: 'complex' };
    const steps = Array.isArray(rule.steps) ? rule.steps : [];
    const windowBars = typeof rule.window_bars === 'number' ? rule.window_bars : null;
    const explainedSteps = steps.map((step) => summarizeRule(step, options, depth + 1).text);

    return explainedSteps.length > 0
      ? { text: `Sequence${windowBars ? ` within ${windowBars} bars` : ''}: ${explainedSteps.join(' -> ')}`, kind: 'complex' }
      : { text: 'Sequence rule', kind: 'complex' };
  }

  return { text: titleCase(typeof rule.type === 'string' ? rule.type : 'Unknown rule'), kind: 'custom' };
}

export function explainRule(rule: unknown, options: RuleSummaryOptions = {}): string {
  return summarizeRule(rule, options).text;
}
