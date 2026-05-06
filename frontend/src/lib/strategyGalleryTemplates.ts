type StrategyStyle = 'Mean reversion' | 'Trend' | 'Risk filter' | 'Overlay' | 'Relative strength';
type RiskLevel = 'Lower' | 'Moderate' | 'Higher';
type ReferenceSeriesUsage = 'None' | 'VIX regime' | 'ETF relative strength' | 'ETF trend filter';

type AllocationSpec = {
  entry_mode: 'percent_of_equity';
  entry_value: number;
  max_position_pct: number;
};

type RiskSpec = {
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  partial_take_profit: null;
  cooldown_bars: number;
};

type CoreOverlaySpec = {
  enabled: boolean;
  core_allocation_pct: number;
};

type PositionManagementSpec = {
  scale_in_fraction: number;
  scale_out_fraction?: number;
  exit_behavior?: 'scale_out' | 'sell_all';
  profit_reduce_threshold?: number | null;
  max_scale_in_steps?: number | null;
  min_bars_between_scale_ins?: number;
  scale_in_requires_persistent_signal?: boolean;
  minimum_trade_notional?: number;
  minimum_trade_pct_of_equity?: number;
  minimum_trade_shares?: number;
};

type AtomicRule = {
  kind: 'atomic';
  type:
    | 'rsi_below'
    | 'rsi_above'
    | 'sma_cross_below'
    | 'sma_above'
    | 'series_below'
    | 'series_above'
    | 'relative_return_above';
  symbol?: string;
  lookback?: number;
  threshold?: number;
  fast_window?: number;
  slow_window?: number;
  reference_symbol?: string;
};

type NotRule = {
  kind: 'not';
  rule: RuleNode;
};

type GroupRule = {
  kind: 'group';
  operator: 'AND' | 'OR';
  rules: RuleNode[];
};

type RuleNode = AtomicRule | NotRule | GroupRule;

export type StrategyV2TemplateConfig = {
  schema_version: '2.0';
  name: string;
  tradable_symbol: string;
  benchmark_symbol: string;
  reference_symbols: string[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  transaction_cost_bps: number;
  allocation: AllocationSpec;
  entry_rule: RuleNode;
  exit_rule: RuleNode;
  risk: RiskSpec;
  core_overlay: CoreOverlaySpec;
  position_management?: PositionManagementSpec | null;
};

export type StrategyGalleryTemplate = {
  id: string;
  title: string;
  shortExplanation: string;
  symbols: string[];
  categoryLabel: string;
  tags: string[];
  style: StrategyStyle;
  riskLevel: RiskLevel;
  strategyFamily: string;
  referenceSeriesUsage: ReferenceSeriesUsage;
  expectedBehavior: string;
  entryRuleText: string;
  exitRuleText: string;
  riskControls: string[];
  config: StrategyV2TemplateConfig;
};

export type StrategyGalleryFilters = {
  query: string;
  style: string;
  riskLevel: string;
  symbol: string;
  referenceSeriesUsage: string;
  tagOrCategory: string;
};

const TEMPLATE_BACKTEST_YEARS = 5;
const TEMPLATE_BACKTEST_SAFETY_DAYS = 3;

function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function shiftDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function shiftYears(value: Date, years: number): Date {
  const next = new Date(value);
  next.setFullYear(next.getFullYear() + years);
  return next;
}

function rollBackToWeekday(value: Date): Date {
  const next = new Date(value);
  const day = next.getDay();
  if (day === 0) return shiftDays(next, -2);
  if (day === 6) return shiftDays(next, -1);
  return next;
}

function rollForwardToWeekday(value: Date): Date {
  const next = new Date(value);
  const day = next.getDay();
  if (day === 0) return shiftDays(next, 1);
  if (day === 6) return shiftDays(next, 2);
  return next;
}

function getDefaultTemplateDateRange(today = new Date()) {
  const localToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const latestSupportedEnd = rollBackToWeekday(localToday);
  const approximateStart = shiftDays(
    shiftYears(latestSupportedEnd, -TEMPLATE_BACKTEST_YEARS),
    TEMPLATE_BACKTEST_SAFETY_DAYS
  );
  const start = rollForwardToWeekday(approximateStart);

  return {
    start_date: toIsoDate(start),
    end_date: toIsoDate(latestSupportedEnd)
  };
}

export const DEFAULT_TEMPLATE_DATE_RANGE = getDefaultTemplateDateRange();

const BASE_CONFIG = {
  schema_version: '2.0',
  ...DEFAULT_TEMPLATE_DATE_RANGE,
  initial_capital: 100000,
  transaction_cost_bps: 5,
  allocation: {
    entry_mode: 'percent_of_equity',
    entry_value: 1.0,
    max_position_pct: 1.0
  },
  risk: {
    stop_loss_pct: 0.1,
    take_profit_pct: null,
    partial_take_profit: null,
    cooldown_bars: 0
  },
  core_overlay: {
    enabled: false,
    core_allocation_pct: 0
  }
} satisfies Pick<
  StrategyV2TemplateConfig,
  | 'schema_version'
  | 'start_date'
  | 'end_date'
  | 'initial_capital'
  | 'transaction_cost_bps'
  | 'allocation'
  | 'risk'
  | 'core_overlay'
>;

export const EMPTY_STRATEGY_GALLERY_FILTERS: StrategyGalleryFilters = {
  query: '',
  style: '',
  riskLevel: '',
  symbol: '',
  referenceSeriesUsage: '',
  tagOrCategory: ''
};

function normalizeSearchValue(value: string): string {
  return value.trim().toLowerCase();
}

function templateSearchText(template: StrategyGalleryTemplate): string {
  return [
    template.title,
    template.shortExplanation,
    template.expectedBehavior,
    template.categoryLabel,
    template.style,
    template.riskLevel,
    template.strategyFamily,
    template.referenceSeriesUsage,
    ...template.symbols,
    ...template.tags
  ]
    .join(' ')
    .toLowerCase();
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values)).sort((left, right) => left.localeCompare(right));
}

function pushUniqueDisplayChip(chips: string[], seen: Set<string>, value: string) {
  const chip = value.trim();
  if (!chip) return;

  const key = chip.toLowerCase();
  if (seen.has(key)) return;

  seen.add(key);
  chips.push(chip);
}

export function getStrategyGalleryFilterOptions(templates: readonly StrategyGalleryTemplate[]) {
  return {
    styles: uniqueSorted(templates.map((template) => template.style)),
    riskLevels: uniqueSorted(templates.map((template) => template.riskLevel)),
    symbols: uniqueSorted(templates.flatMap((template) => template.symbols)),
    referenceSeriesUsages: uniqueSorted(templates.map((template) => template.referenceSeriesUsage)),
    tagsAndCategories: uniqueSorted(
      templates.flatMap((template) => [template.categoryLabel, ...template.tags])
    )
  };
}

export function getStrategyGalleryDisplayChips(template: StrategyGalleryTemplate): string[] {
  const chips: string[] = [];
  const seen = new Set<string>();
  const referenceSymbols = template.config.reference_symbols.filter(
    (symbol) => !template.symbols.some((displaySymbol) => displaySymbol.toLowerCase() === symbol.toLowerCase())
  );

  for (const symbol of template.symbols) {
    pushUniqueDisplayChip(chips, seen, symbol);
  }
  for (const symbol of referenceSymbols) {
    pushUniqueDisplayChip(chips, seen, symbol);
  }
  pushUniqueDisplayChip(chips, seen, template.categoryLabel);
  for (const tag of template.tags) {
    pushUniqueDisplayChip(chips, seen, tag);
  }

  return chips;
}

export function hasActiveStrategyGalleryFilters(filters: StrategyGalleryFilters): boolean {
  return Object.values(filters).some((value) => value.trim() !== '');
}

export function filterStrategyGalleryTemplates(
  templates: readonly StrategyGalleryTemplate[],
  filters: StrategyGalleryFilters
): StrategyGalleryTemplate[] {
  const query = normalizeSearchValue(filters.query);

  return templates.filter((template) => {
    if (query && !templateSearchText(template).includes(query)) return false;
    if (filters.style && template.style !== filters.style) return false;
    if (filters.riskLevel && template.riskLevel !== filters.riskLevel) return false;
    if (filters.symbol && !template.symbols.includes(filters.symbol)) return false;
    if (filters.referenceSeriesUsage && template.referenceSeriesUsage !== filters.referenceSeriesUsage) {
      return false;
    }
    if (
      filters.tagOrCategory &&
      template.categoryLabel !== filters.tagOrCategory &&
      !template.tags.includes(filters.tagOrCategory)
    ) {
      return false;
    }

    return true;
  });
}

export const STRATEGY_GALLERY_TEMPLATES = [
  {
    id: 'qqq-rsi-mean-reversion',
    title: 'QQQ RSI Mean Reversion',
    shortExplanation: 'Tests a simple QQQ pullback idea using RSI oversold entries and RSI recovery exits.',
    symbols: ['QQQ'],
    categoryLabel: 'Pullback',
    tags: ['QQQ', 'RSI', 'scale-in', 'sell-all'],
    style: 'Mean reversion',
    riskLevel: 'Moderate',
    strategyFamily: 'RSI pullback',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Enters 25% at a time while RSI stays oversold, waits between adds, skips very small trades, and sells the full position when RSI recovers.',
    entryRuleText: 'Enter QQQ when RSI(14) falls below 35.',
    exitRuleText: 'Exit the full QQQ position when RSI(14) rises above 65.',
    riskControls: ['10% stop loss', '25% entries', 'Up to 4 entries', '3-bar wait between adds', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ RSI Mean Reversion',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: [],
      entry_rule: {
        kind: 'atomic',
        type: 'rsi_below',
        symbol: 'QQQ',
        lookback: 14,
        threshold: 35
      },
      exit_rule: {
        kind: 'atomic',
        type: 'rsi_above',
        symbol: 'QQQ',
        lookback: 14,
        threshold: 65
      },
      position_management: {
        scale_in_fraction: 0.25,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 4,
        min_bars_between_scale_ins: 3,
        scale_in_requires_persistent_signal: true,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'qqq-vix-risk-on-risk-off',
    title: 'QQQ VIX Risk-On/Risk-Off',
    shortExplanation: 'Tests a volatility-filtered QQQ pullback: buy only when VIX is calmer and QQQ is oversold.',
    symbols: ['QQQ', 'VIX'],
    categoryLabel: 'Volatility regime',
    tags: ['QQQ', 'VIX', 'RSI', 'risk filter'],
    style: 'Risk filter',
    riskLevel: 'Moderate',
    strategyFamily: 'Volatility-filtered pullback',
    referenceSeriesUsage: 'VIX regime',
    expectedBehavior: 'Uses VIX as a risk filter, scales into qualifying RSI pullbacks, skips very small trades, and sells all when volatility spikes or RSI rebounds.',
    entryRuleText: 'Enter when VIX is below 25 and QQQ RSI(14) is below 40.',
    exitRuleText: 'Exit the full QQQ position when VIX rises above 35 or QQQ RSI(14) rises above 70.',
    riskControls: ['10% stop loss', 'VIX regime filter', '25% entries', 'Up to 3 entries', '3-bar wait between adds', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ VIX Risk-On Risk-Off',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: ['VIX'],
      entry_rule: {
        kind: 'group',
        operator: 'AND',
        rules: [
          {
            kind: 'atomic',
            type: 'series_below',
            symbol: 'VIX',
            threshold: 25
          },
          {
            kind: 'atomic',
            type: 'rsi_below',
            symbol: 'QQQ',
            lookback: 14,
            threshold: 40
          }
        ]
      },
      exit_rule: {
        kind: 'group',
        operator: 'OR',
        rules: [
          {
            kind: 'atomic',
            type: 'series_above',
            symbol: 'VIX',
            threshold: 35
          },
          {
            kind: 'atomic',
            type: 'rsi_above',
            symbol: 'QQQ',
            lookback: 14,
            threshold: 70
          }
        ]
      },
      position_management: {
        scale_in_fraction: 0.25,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 3,
        min_bars_between_scale_ins: 3,
        scale_in_requires_persistent_signal: true,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'qqq-core-vix-overlay',
    title: 'QQQ Core + VIX Tactical Overlay',
    shortExplanation: 'Tests a 60% QQQ core with a tactical overlay that turns on only in calmer VIX regimes.',
    symbols: ['QQQ', 'VIX'],
    categoryLabel: 'Core overlay',
    tags: ['QQQ', 'VIX', 'core sleeve', 'overlay'],
    style: 'Overlay',
    riskLevel: 'Moderate',
    strategyFamily: 'Core plus tactical overlay',
    referenceSeriesUsage: 'VIX regime',
    expectedBehavior: 'Keeps the core sleeve invested while the overlay adds exposure below the VIX threshold and sells the overlay when volatility rises.',
    entryRuleText: 'Keep a 60% QQQ core. Add overlay exposure when VIX is below 15.',
    exitRuleText: 'Sell the tactical overlay when VIX rises above 35; the QQQ core stays invested.',
    riskControls: ['60% core allocation', '40% tactical sleeve', 'Full overlay exit above VIX 35', 'Skips overlay trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ Core VIX Tactical Overlay',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: ['VIX'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.6
      },
      entry_rule: {
        kind: 'atomic',
        type: 'series_below',
        symbol: 'VIX',
        threshold: 15
      },
      exit_rule: {
        kind: 'atomic',
        type: 'series_above',
        symbol: 'VIX',
        threshold: 35
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'spy-moving-average-trend-filter',
    title: 'SPY Moving Average Trend Filter',
    shortExplanation: 'Tests whether SPY exposure should only be active while price remains above its 200-day average.',
    symbols: ['SPY'],
    categoryLabel: 'Trend following',
    tags: ['SPY', 'SMA', 'trend state', 'sell-all'],
    style: 'Trend',
    riskLevel: 'Lower',
    strategyFamily: 'Moving average trend',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Uses one full-sized trend entry, skips very small trades, and sells all when SPY breaks below its long-term average.',
    entryRuleText: 'Enter SPY when price is above its 200-day SMA.',
    exitRuleText: 'Exit the full SPY position when price crosses below its 200-day SMA.',
    riskControls: ['Trend-state filter', 'Single full entry', 'Full exit on trend break', '10% stop loss', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'SPY Moving Average Trend Filter',
      tradable_symbol: 'SPY',
      benchmark_symbol: 'SPY',
      reference_symbols: [],
      entry_rule: {
        kind: 'atomic',
        type: 'sma_above',
        symbol: 'SPY',
        fast_window: 1,
        slow_window: 200
      },
      exit_rule: {
        kind: 'atomic',
        type: 'sma_cross_below',
        symbol: 'SPY',
        fast_window: 1,
        slow_window: 200
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'xlk-sector-relative-strength',
    title: 'XLK Sector Relative Strength',
    shortExplanation: 'Tests a supported sector-style idea by trading XLK only when it leads SPY over a 60-day window.',
    symbols: ['XLK', 'SPY'],
    categoryLabel: 'Sector rotation',
    tags: ['XLK', 'SPY', 'relative strength', 'sector'],
    style: 'Relative strength',
    riskLevel: 'Higher',
    strategyFamily: 'Sector relative strength',
    referenceSeriesUsage: 'ETF relative strength',
    expectedBehavior: 'Uses one full-sized XLK entry when it leads SPY, skips very small trades, and sells all when that leadership fades.',
    entryRuleText: 'Enter XLK when XLK outperforms SPY by more than 3% over 60 trading days.',
    exitRuleText: 'Exit the full XLK position when XLK no longer outperforms SPY by more than 3% over 60 trading days.',
    riskControls: ['Relative strength confirmation', 'Single full entry', 'Full exit when leadership fades', '10% stop loss', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'XLK Sector Relative Strength',
      tradable_symbol: 'XLK',
      benchmark_symbol: 'SPY',
      reference_symbols: ['SPY'],
      entry_rule: {
        kind: 'atomic',
        type: 'relative_return_above',
        symbol: 'XLK',
        reference_symbol: 'SPY',
        lookback: 60,
        threshold: 0.03
      },
      exit_rule: {
        kind: 'not',
        rule: {
          kind: 'atomic',
          type: 'relative_return_above',
          symbol: 'XLK',
          reference_symbol: 'SPY',
          lookback: 60,
          threshold: 0.03
        }
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'qqq-tlt-defensive-relative-strength',
    title: 'QQQ / TLT Defensive Relative Strength',
    shortExplanation: 'Tests staying in QQQ only when it leads long-duration Treasuries over a medium-term window.',
    symbols: ['QQQ', 'TLT'],
    categoryLabel: 'Defensive filter',
    tags: ['QQQ', 'TLT', 'defensive', 'relative strength'],
    style: 'Risk filter',
    riskLevel: 'Higher',
    strategyFamily: 'Defensive relative strength',
    referenceSeriesUsage: 'ETF relative strength',
    expectedBehavior: 'Uses one full-sized QQQ entry while it leads TLT, skips very small trades, and sells all when defensive strength takes over.',
    entryRuleText: 'Enter QQQ when QQQ outperforms TLT over 60 trading days.',
    exitRuleText: 'Exit the full QQQ position when QQQ no longer outperforms TLT over 60 trading days.',
    riskControls: ['Defensive relative strength filter', 'Single full entry', 'Full exit when QQQ leadership fades', '10% stop loss', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ TLT Defensive Relative Strength',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: ['TLT'],
      entry_rule: {
        kind: 'atomic',
        type: 'relative_return_above',
        symbol: 'QQQ',
        reference_symbol: 'TLT',
        lookback: 60,
        threshold: 0
      },
      exit_rule: {
        kind: 'not',
        rule: {
          kind: 'atomic',
          type: 'relative_return_above',
          symbol: 'QQQ',
          reference_symbol: 'TLT',
          lookback: 60,
          threshold: 0
        }
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'spy-rsi-strict-pullback',
    title: 'SPY RSI Pullback with Tighter Risk',
    shortExplanation: 'Tests a stricter SPY pullback idea with smaller entries, a tighter stop, and a cooldown after exits.',
    symbols: ['SPY'],
    categoryLabel: 'Pullback',
    tags: ['SPY', 'RSI', 'cooldown', 'tighter stop'],
    style: 'Mean reversion',
    riskLevel: 'Lower',
    strategyFamily: 'RSI pullback',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Adds in smaller 20% steps during deeper RSI pullbacks, waits between adds, and sells all on a moderate RSI recovery.',
    entryRuleText: 'Enter SPY when RSI(14) falls below 30.',
    exitRuleText: 'Exit the full SPY position when RSI(14) rises above 55.',
    riskControls: ['6% stop loss', '20% entries', 'Up to 3 entries', '5-bar wait between adds', '2-bar cooldown', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'SPY RSI Pullback with Tighter Risk',
      tradable_symbol: 'SPY',
      benchmark_symbol: 'SPY',
      reference_symbols: [],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.06,
        cooldown_bars: 2
      },
      entry_rule: {
        kind: 'atomic',
        type: 'rsi_below',
        symbol: 'SPY',
        lookback: 14,
        threshold: 30
      },
      exit_rule: {
        kind: 'atomic',
        type: 'rsi_above',
        symbol: 'SPY',
        lookback: 14,
        threshold: 55
      },
      position_management: {
        scale_in_fraction: 0.2,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 3,
        min_bars_between_scale_ins: 5,
        scale_in_requires_persistent_signal: true,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'qqq-50-200-trend-following',
    title: 'QQQ 50/200 Trend Following',
    shortExplanation: 'Tests QQQ exposure only when the shorter moving average is above the longer trend average.',
    symbols: ['QQQ'],
    categoryLabel: 'Trend following',
    tags: ['QQQ', 'SMA', '50-day', '200-day'],
    style: 'Trend',
    riskLevel: 'Moderate',
    strategyFamily: 'Moving average trend',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Uses a single full entry when QQQ is in an uptrend and exits fully when the trend relationship breaks.',
    entryRuleText: 'Enter QQQ when its 50-day SMA is above its 200-day SMA.',
    exitRuleText: 'Exit the full QQQ position when its 50-day SMA crosses below its 200-day SMA.',
    riskControls: ['50/200 trend filter', 'Single full entry', 'Full exit on trend break', '8% stop loss', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ 50 200 Trend Following',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: [],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.08
      },
      entry_rule: {
        kind: 'atomic',
        type: 'sma_above',
        symbol: 'QQQ',
        fast_window: 50,
        slow_window: 200
      },
      exit_rule: {
        kind: 'atomic',
        type: 'sma_cross_below',
        symbol: 'QQQ',
        fast_window: 50,
        slow_window: 200
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'spy-vix-rsi-regime-pullback',
    title: 'SPY VIX Regime + RSI Pullback',
    shortExplanation: 'Tests SPY pullbacks only when VIX is below a defined stress threshold.',
    symbols: ['SPY', 'VIX'],
    categoryLabel: 'Volatility regime',
    tags: ['SPY', 'VIX', 'RSI', 'regime'],
    style: 'Risk filter',
    riskLevel: 'Moderate',
    strategyFamily: 'Volatility-filtered pullback',
    referenceSeriesUsage: 'VIX regime',
    expectedBehavior: 'Scales into SPY pullbacks while VIX remains contained and exits fully on either a volatility spike or RSI recovery.',
    entryRuleText: 'Enter when VIX is below 22 and SPY RSI(14) is below 38.',
    exitRuleText: 'Exit the full SPY position when VIX rises above 30 or SPY RSI(14) rises above 62.',
    riskControls: ['8% stop loss', 'VIX regime filter', '25% entries', 'Up to 3 entries', '3-bar wait between adds', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'SPY VIX Regime RSI Pullback',
      tradable_symbol: 'SPY',
      benchmark_symbol: 'SPY',
      reference_symbols: ['VIX'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.08
      },
      entry_rule: {
        kind: 'group',
        operator: 'AND',
        rules: [
          {
            kind: 'atomic',
            type: 'series_below',
            symbol: 'VIX',
            threshold: 22
          },
          {
            kind: 'atomic',
            type: 'rsi_below',
            symbol: 'SPY',
            lookback: 14,
            threshold: 38
          }
        ]
      },
      exit_rule: {
        kind: 'group',
        operator: 'OR',
        rules: [
          {
            kind: 'atomic',
            type: 'series_above',
            symbol: 'VIX',
            threshold: 30
          },
          {
            kind: 'atomic',
            type: 'rsi_above',
            symbol: 'SPY',
            lookback: 14,
            threshold: 62
          }
        ]
      },
      position_management: {
        scale_in_fraction: 0.25,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 3,
        min_bars_between_scale_ins: 3,
        scale_in_requires_persistent_signal: true,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'spy-core-defensive-vix-overlay',
    title: 'SPY Core Defensive VIX Overlay',
    shortExplanation: 'Tests a SPY core with tactical exposure added only when trend and VIX conditions agree.',
    symbols: ['SPY', 'VIX'],
    categoryLabel: 'Core overlay',
    tags: ['SPY', 'VIX', 'SMA', 'core sleeve'],
    style: 'Overlay',
    riskLevel: 'Lower',
    strategyFamily: 'Core plus tactical overlay',
    referenceSeriesUsage: 'VIX regime',
    expectedBehavior: 'Keeps a 50% SPY core while the tactical sleeve requires both a positive trend state and contained volatility.',
    entryRuleText: 'Keep a 50% SPY core. Add overlay exposure when SPY is above its 200-day SMA and VIX is below 22.',
    exitRuleText: 'Sell the tactical overlay when SPY crosses below its 200-day SMA or VIX rises above 32.',
    riskControls: ['50% core allocation', '50% tactical sleeve', 'Trend and VIX filters', 'Full overlay exit on risk-off signal', 'Skips overlay trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'SPY Core Defensive VIX Overlay',
      tradable_symbol: 'SPY',
      benchmark_symbol: 'SPY',
      reference_symbols: ['VIX'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.5
      },
      entry_rule: {
        kind: 'group',
        operator: 'AND',
        rules: [
          {
            kind: 'atomic',
            type: 'sma_above',
            symbol: 'SPY',
            fast_window: 1,
            slow_window: 200
          },
          {
            kind: 'atomic',
            type: 'series_below',
            symbol: 'VIX',
            threshold: 22
          }
        ]
      },
      exit_rule: {
        kind: 'group',
        operator: 'OR',
        rules: [
          {
            kind: 'atomic',
            type: 'sma_cross_below',
            symbol: 'SPY',
            fast_window: 1,
            slow_window: 200
          },
          {
            kind: 'atomic',
            type: 'series_above',
            symbol: 'VIX',
            threshold: 32
          }
        ]
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'xlu-defensive-sector-relative-strength',
    title: 'XLU Defensive Sector Relative Strength',
    shortExplanation: 'Tests a defensive sector sleeve by trading XLU only when it leads SPY over a 60-day window.',
    symbols: ['XLU', 'SPY'],
    categoryLabel: 'Sector rotation',
    tags: ['XLU', 'SPY', 'defensive', 'relative strength'],
    style: 'Relative strength',
    riskLevel: 'Moderate',
    strategyFamily: 'Sector relative strength',
    referenceSeriesUsage: 'ETF relative strength',
    expectedBehavior: 'Uses one full-sized XLU entry when it leads SPY and exits fully when that relative strength condition fades.',
    entryRuleText: 'Enter XLU when XLU outperforms SPY by more than 1% over 60 trading days.',
    exitRuleText: 'Exit the full XLU position when XLU no longer outperforms SPY by more than 1% over 60 trading days.',
    riskControls: ['Relative strength confirmation', 'Single full entry', 'Full exit when leadership fades', '8% stop loss', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'XLU Defensive Sector Relative Strength',
      tradable_symbol: 'XLU',
      benchmark_symbol: 'SPY',
      reference_symbols: ['SPY'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.08
      },
      entry_rule: {
        kind: 'atomic',
        type: 'relative_return_above',
        symbol: 'XLU',
        reference_symbol: 'SPY',
        lookback: 60,
        threshold: 0.01
      },
      exit_rule: {
        kind: 'not',
        rule: {
          kind: 'atomic',
          type: 'relative_return_above',
          symbol: 'XLU',
          reference_symbol: 'SPY',
          lookback: 60,
          threshold: 0.01
        }
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'qqq-ief-trend-filtered-pullback',
    title: 'QQQ Pullback with IEF Trend Filter',
    shortExplanation: 'Tests QQQ pullbacks only while intermediate Treasuries remain in a positive trend state.',
    symbols: ['QQQ', 'IEF'],
    categoryLabel: 'Defensive filter',
    tags: ['QQQ', 'IEF', 'RSI', 'Treasury filter'],
    style: 'Risk filter',
    riskLevel: 'Moderate',
    strategyFamily: 'Defensive trend filter',
    referenceSeriesUsage: 'ETF trend filter',
    expectedBehavior: 'Scales into QQQ pullbacks while IEF stays above its trend filter and exits fully on RSI recovery or a defensive trend break.',
    entryRuleText: 'Enter when QQQ RSI(14) is below 40 and IEF is above its 100-day SMA.',
    exitRuleText: 'Exit the full QQQ position when QQQ RSI(14) rises above 62 or IEF crosses below its 100-day SMA.',
    riskControls: ['8% stop loss', 'IEF trend filter', '25% entries', 'Up to 3 entries', '3-bar wait between adds', 'Skips trades below $500', '5 bps transaction cost'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ Pullback with IEF Trend Filter',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: ['IEF'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.08
      },
      entry_rule: {
        kind: 'group',
        operator: 'AND',
        rules: [
          {
            kind: 'atomic',
            type: 'rsi_below',
            symbol: 'QQQ',
            lookback: 14,
            threshold: 40
          },
          {
            kind: 'atomic',
            type: 'sma_above',
            symbol: 'IEF',
            fast_window: 1,
            slow_window: 100
          }
        ]
      },
      exit_rule: {
        kind: 'group',
        operator: 'OR',
        rules: [
          {
            kind: 'atomic',
            type: 'rsi_above',
            symbol: 'QQQ',
            lookback: 14,
            threshold: 62
          },
          {
            kind: 'atomic',
            type: 'sma_cross_below',
            symbol: 'IEF',
            fast_window: 1,
            slow_window: 100
          }
        ]
      },
      position_management: {
        scale_in_fraction: 0.25,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 3,
        min_bars_between_scale_ins: 3,
        scale_in_requires_persistent_signal: true,
        minimum_trade_notional: 500
      }
    }
  }
] as const satisfies readonly StrategyGalleryTemplate[];

export function findStrategyGalleryTemplate(templateId: string | null): StrategyGalleryTemplate | null {
  if (!templateId) return null;
  return STRATEGY_GALLERY_TEMPLATES.find((template) => template.id === templateId) ?? null;
}
