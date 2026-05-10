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
    id: 'xle-rsi-defensive-pullback',
    title: 'XLE RSI Defensive Pullback',
    shortExplanation: 'Historically screened XLE RSI pullback research with a capped position size and cooldown.',
    symbols: ['XLE'],
    categoryLabel: 'Sector pullback',
    tags: ['XLE', 'RSI', 'defensive', 'cooldown'],
    style: 'Mean reversion',
    riskLevel: 'Moderate',
    strategyFamily: 'RSI mean reversion',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Uses 25% scale-ins up to a 75% cap, exits fully on RSI recovery, and is framed as defensive research; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Enter XLE when RSI(14) falls below 45.',
    exitRuleText: 'Exit the full XLE position when RSI(14) rises above 60.',
    riskControls: ['12% stop loss', '25% entries', '75% max position', '3-bar wait between adds', '5-bar cooldown', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'XLE RSI Defensive Pullback',
      tradable_symbol: 'XLE',
      benchmark_symbol: 'XLE',
      reference_symbols: [],
      allocation: {
        ...BASE_CONFIG.allocation,
        max_position_pct: 0.75
      },
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.12,
        cooldown_bars: 5
      },
      entry_rule: {
        kind: 'atomic',
        type: 'rsi_below',
        symbol: 'XLE',
        lookback: 14,
        threshold: 45
      },
      exit_rule: {
        kind: 'atomic',
        type: 'rsi_above',
        symbol: 'XLE',
        lookback: 14,
        threshold: 60
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
    id: 'iwm-rsi-defensive-pullback',
    title: 'IWM RSI Defensive Pullback',
    shortExplanation: 'Historically screened small-cap RSI pullback candidate with explicit stop and cooldown settings.',
    symbols: ['IWM'],
    categoryLabel: 'Small-cap pullback',
    tags: ['IWM', 'RSI', 'defensive', 'small cap'],
    style: 'Mean reversion',
    riskLevel: 'Moderate',
    strategyFamily: 'RSI mean reversion',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Uses 25% scale-ins, an 8% stop, and full exits on RSI recovery; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Enter IWM when RSI(14) falls below 45.',
    exitRuleText: 'Exit the full IWM position when RSI(14) rises above 70.',
    riskControls: ['8% stop loss', '25% entries', 'Up to 3 entries', '3-bar wait between adds', '3-bar cooldown', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'IWM RSI Defensive Pullback',
      tradable_symbol: 'IWM',
      benchmark_symbol: 'IWM',
      reference_symbols: [],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.08,
        cooldown_bars: 3
      },
      entry_rule: {
        kind: 'atomic',
        type: 'rsi_below',
        symbol: 'IWM',
        lookback: 14,
        threshold: 45
      },
      exit_rule: {
        kind: 'atomic',
        type: 'rsi_above',
        symbol: 'IWM',
        lookback: 14,
        threshold: 70
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
    id: 'qqq-core-vix-trend-overlay',
    title: 'QQQ Core VIX Trend Overlay',
    shortExplanation: 'Major ETF starter example using a QQQ core plus a VIX and trend-gated tactical sleeve.',
    symbols: ['QQQ', 'VIX'],
    categoryLabel: 'Major ETF starter',
    tags: ['QQQ', 'VIX', 'trend filter', 'core sleeve'],
    style: 'Overlay',
    riskLevel: 'Moderate',
    strategyFamily: 'Core VIX trend overlay',
    referenceSeriesUsage: 'VIX regime',
    expectedBehavior: 'Keeps an 80% QQQ core while the overlay requires VIX below 30 and price above its 100-day SMA; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Keep an 80% QQQ core. Add overlay exposure when VIX is below 30 and QQQ is above its 100-day SMA.',
    exitRuleText: 'Sell the tactical overlay when QQQ crosses below its 100-day SMA.',
    riskControls: ['80% core allocation', 'VIX below 30 entry filter', '100-day SMA trend filter', 'Single full overlay entry', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ Core VIX Trend Overlay',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: ['VIX'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.8
      },
      entry_rule: {
        kind: 'group',
        operator: 'AND',
        rules: [
          {
            kind: 'atomic',
            type: 'series_below',
            symbol: 'VIX',
            threshold: 30
          },
          {
            kind: 'atomic',
            type: 'sma_above',
            symbol: 'QQQ',
            fast_window: 1,
            slow_window: 100
          }
        ]
      },
      exit_rule: {
        kind: 'atomic',
        type: 'sma_cross_below',
        symbol: 'QQQ',
        fast_window: 1,
        slow_window: 100
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        min_bars_between_scale_ins: 0,
        scale_in_requires_persistent_signal: false,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'spy-core-vix-trend-overlay',
    title: 'SPY Core VIX Trend Overlay',
    shortExplanation: 'Major ETF risk-control example using a SPY core plus a VIX and trend-gated tactical sleeve.',
    symbols: ['SPY', 'VIX'],
    categoryLabel: 'Major ETF starter',
    tags: ['SPY', 'VIX', 'trend filter', 'core sleeve', 'risk control'],
    style: 'Overlay',
    riskLevel: 'Lower',
    strategyFamily: 'Core VIX trend overlay',
    referenceSeriesUsage: 'VIX regime',
    expectedBehavior: 'Keeps an 80% SPY core while the overlay requires VIX below 30 and price above its 100-day SMA; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Keep an 80% SPY core. Add overlay exposure when VIX is below 30 and SPY is above its 100-day SMA.',
    exitRuleText: 'Sell the tactical overlay when SPY crosses below its 100-day SMA.',
    riskControls: ['80% core allocation', 'VIX below 30 entry filter', '100-day SMA trend filter', 'Single full overlay entry', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'SPY Core VIX Trend Overlay',
      tradable_symbol: 'SPY',
      benchmark_symbol: 'SPY',
      reference_symbols: ['VIX'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.8
      },
      entry_rule: {
        kind: 'group',
        operator: 'AND',
        rules: [
          {
            kind: 'atomic',
            type: 'series_below',
            symbol: 'VIX',
            threshold: 30
          },
          {
            kind: 'atomic',
            type: 'sma_above',
            symbol: 'SPY',
            fast_window: 1,
            slow_window: 100
          }
        ]
      },
      exit_rule: {
        kind: 'atomic',
        type: 'sma_cross_below',
        symbol: 'SPY',
        fast_window: 1,
        slow_window: 100
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        min_bars_between_scale_ins: 0,
        scale_in_requires_persistent_signal: false,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'xlv-rsi-healthcare-risk-control',
    title: 'XLV RSI Healthcare Risk-Control',
    shortExplanation: 'Healthcare sector pullback research candidate selected for drawdown-aware behavior, not outperformance.',
    symbols: ['XLV'],
    categoryLabel: 'Sector pullback',
    tags: ['XLV', 'RSI', 'healthcare', 'risk control'],
    style: 'Mean reversion',
    riskLevel: 'Lower',
    strategyFamily: 'RSI mean reversion',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Uses 25% scale-ins with an 8% stop and full exits on RSI recovery; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Enter XLV when RSI(14) falls below 35.',
    exitRuleText: 'Exit the full XLV position when RSI(14) rises above 70.',
    riskControls: ['8% stop loss', '25% entries', 'Up to 3 entries', '3-bar wait between adds', '3-bar cooldown', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'XLV RSI Healthcare Risk Control',
      tradable_symbol: 'XLV',
      benchmark_symbol: 'XLV',
      reference_symbols: [],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: 0.08,
        cooldown_bars: 3
      },
      entry_rule: {
        kind: 'atomic',
        type: 'rsi_below',
        symbol: 'XLV',
        lookback: 14,
        threshold: 35
      },
      exit_rule: {
        kind: 'atomic',
        type: 'rsi_above',
        symbol: 'XLV',
        lookback: 14,
        threshold: 70
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
    id: 'xlp-core-relative-strength-overlay',
    title: 'XLP Core Relative Strength Overlay',
    shortExplanation: 'Defensive sector overlay research using a staples core and a relative-strength tactical sleeve.',
    symbols: ['XLP', 'SPY'],
    categoryLabel: 'Sector overlay',
    tags: ['XLP', 'SPY', 'relative strength', 'defensive'],
    style: 'Relative strength',
    riskLevel: 'Lower',
    strategyFamily: 'Sector core relative strength',
    referenceSeriesUsage: 'ETF relative strength',
    expectedBehavior: 'Keeps a 50% XLP core and adds the overlay only while XLP has stronger 30-day return than SPY; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Keep a 50% XLP core. Add overlay exposure when XLP has stronger 30-day return than SPY.',
    exitRuleText: 'Sell the tactical overlay when XLP no longer has stronger 30-day return than SPY.',
    riskControls: ['50% core allocation', '30-day relative-strength filter', 'Single full overlay entry', 'Full overlay exit when leadership fades', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'XLP Core Relative Strength Overlay',
      tradable_symbol: 'XLP',
      benchmark_symbol: 'SPY',
      reference_symbols: ['SPY'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.5
      },
      entry_rule: {
        kind: 'atomic',
        type: 'relative_return_above',
        symbol: 'XLP',
        reference_symbol: 'SPY',
        lookback: 30,
        threshold: 0
      },
      exit_rule: {
        kind: 'not',
        rule: {
          kind: 'atomic',
          type: 'relative_return_above',
          symbol: 'XLP',
          reference_symbol: 'SPY',
          lookback: 30,
          threshold: 0
        }
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        min_bars_between_scale_ins: 0,
        scale_in_requires_persistent_signal: false,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'xli-core-relative-strength-watchlist',
    title: 'XLI Core Relative Strength Watchlist',
    shortExplanation: 'Industrials watchlist example from the discovery report, kept as relative-strength research.',
    symbols: ['XLI', 'SPY'],
    categoryLabel: 'Sector overlay',
    tags: ['XLI', 'SPY', 'relative strength', 'watchlist'],
    style: 'Relative strength',
    riskLevel: 'Lower',
    strategyFamily: 'Sector core relative strength',
    referenceSeriesUsage: 'ETF relative strength',
    expectedBehavior: 'Keeps an 80% XLI core and adds the overlay only while XLI has stronger 60-day return than SPY; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Keep an 80% XLI core. Add overlay exposure when XLI has stronger 60-day return than SPY.',
    exitRuleText: 'Sell the tactical overlay when XLI no longer has stronger 60-day return than SPY.',
    riskControls: ['80% core allocation', '60-day relative-strength filter', 'Single full overlay entry', 'Full overlay exit when leadership fades', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'XLI Core Relative Strength Watchlist',
      tradable_symbol: 'XLI',
      benchmark_symbol: 'SPY',
      reference_symbols: ['SPY'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.8
      },
      entry_rule: {
        kind: 'atomic',
        type: 'relative_return_above',
        symbol: 'XLI',
        reference_symbol: 'SPY',
        lookback: 60,
        threshold: 0
      },
      exit_rule: {
        kind: 'not',
        rule: {
          kind: 'atomic',
          type: 'relative_return_above',
          symbol: 'XLI',
          reference_symbol: 'SPY',
          lookback: 60,
          threshold: 0
        }
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        min_bars_between_scale_ins: 0,
        scale_in_requires_persistent_signal: false,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'qqq-core-rsi-starter',
    title: 'QQQ Core RSI Starter',
    shortExplanation: 'Major ETF starter example that keeps a QQQ core and uses RSI for the tactical sleeve.',
    symbols: ['QQQ'],
    categoryLabel: 'Major ETF starter',
    tags: ['QQQ', 'RSI', 'core sleeve', 'starter'],
    style: 'Overlay',
    riskLevel: 'Moderate',
    strategyFamily: 'Core RSI overlay',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Keeps an 80% QQQ core, adds two 50% overlay steps on RSI pullbacks, and exits the overlay on RSI recovery; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Keep an 80% QQQ core. Add overlay exposure when QQQ RSI(14) falls below 40.',
    exitRuleText: 'Exit the QQQ tactical overlay when RSI(14) rises above 70.',
    riskControls: ['80% core allocation', '50% overlay entries', 'Up to 2 entries', '3-bar wait between adds', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'QQQ Core RSI Starter',
      tradable_symbol: 'QQQ',
      benchmark_symbol: 'QQQ',
      reference_symbols: [],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.8
      },
      entry_rule: {
        kind: 'atomic',
        type: 'rsi_below',
        symbol: 'QQQ',
        lookback: 14,
        threshold: 40
      },
      exit_rule: {
        kind: 'atomic',
        type: 'rsi_above',
        symbol: 'QQQ',
        lookback: 14,
        threshold: 70
      },
      position_management: {
        scale_in_fraction: 0.5,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 2,
        min_bars_between_scale_ins: 3,
        scale_in_requires_persistent_signal: true,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'spy-core-rsi-starter',
    title: 'SPY Core RSI Starter',
    shortExplanation: 'Major ETF starter example that keeps a SPY core and uses RSI for the tactical sleeve.',
    symbols: ['SPY'],
    categoryLabel: 'Major ETF starter',
    tags: ['SPY', 'RSI', 'core sleeve', 'starter'],
    style: 'Overlay',
    riskLevel: 'Lower',
    strategyFamily: 'Core RSI overlay',
    referenceSeriesUsage: 'None',
    expectedBehavior: 'Keeps an 80% SPY core, adds two 50% overlay steps on RSI pullbacks, and exits the overlay on RSI recovery; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Keep an 80% SPY core. Add overlay exposure when SPY RSI(14) falls below 40.',
    exitRuleText: 'Exit the SPY tactical overlay when RSI(14) rises above 70.',
    riskControls: ['80% core allocation', '50% overlay entries', 'Up to 2 entries', '3-bar wait between adds', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'SPY Core RSI Starter',
      tradable_symbol: 'SPY',
      benchmark_symbol: 'SPY',
      reference_symbols: [],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.8
      },
      entry_rule: {
        kind: 'atomic',
        type: 'rsi_below',
        symbol: 'SPY',
        lookback: 14,
        threshold: 40
      },
      exit_rule: {
        kind: 'atomic',
        type: 'rsi_above',
        symbol: 'SPY',
        lookback: 14,
        threshold: 70
      },
      position_management: {
        scale_in_fraction: 0.5,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 2,
        min_bars_between_scale_ins: 3,
        scale_in_requires_persistent_signal: true,
        minimum_trade_notional: 500
      }
    }
  },
  {
    id: 'xlre-core-relative-strength-defensive',
    title: 'XLRE Core Relative Strength Defensive',
    shortExplanation: 'Real estate sector defensive overlay research selected from gallery-ready discovery candidates.',
    symbols: ['XLRE', 'SPY'],
    categoryLabel: 'Sector overlay',
    tags: ['XLRE', 'SPY', 'relative strength', 'defensive'],
    style: 'Relative strength',
    riskLevel: 'Lower',
    strategyFamily: 'Sector core relative strength',
    referenceSeriesUsage: 'ETF relative strength',
    expectedBehavior: 'Keeps a 50% XLRE core and adds the overlay only while XLRE has stronger 60-day return than SPY; the recent holdout trailed buy-and-hold.',
    entryRuleText: 'Keep a 50% XLRE core. Add overlay exposure when XLRE has stronger 60-day return than SPY.',
    exitRuleText: 'Sell the tactical overlay when XLRE no longer has stronger 60-day return than SPY.',
    riskControls: ['50% core allocation', '60-day relative-strength filter', 'Single full overlay entry', 'Full overlay exit when leadership fades', 'Skips trades below $500'],
    config: {
      ...BASE_CONFIG,
      name: 'XLRE Core Relative Strength Defensive',
      tradable_symbol: 'XLRE',
      benchmark_symbol: 'SPY',
      reference_symbols: ['SPY'],
      risk: {
        ...BASE_CONFIG.risk,
        stop_loss_pct: null
      },
      core_overlay: {
        enabled: true,
        core_allocation_pct: 0.5
      },
      entry_rule: {
        kind: 'atomic',
        type: 'relative_return_above',
        symbol: 'XLRE',
        reference_symbol: 'SPY',
        lookback: 60,
        threshold: 0
      },
      exit_rule: {
        kind: 'not',
        rule: {
          kind: 'atomic',
          type: 'relative_return_above',
          symbol: 'XLRE',
          reference_symbol: 'SPY',
          lookback: 60,
          threshold: 0
        }
      },
      position_management: {
        scale_in_fraction: 1.0,
        exit_behavior: 'sell_all',
        profit_reduce_threshold: null,
        max_scale_in_steps: 1,
        min_bars_between_scale_ins: 0,
        scale_in_requires_persistent_signal: false,
        minimum_trade_notional: 500
      }
    }
  }
] as const satisfies readonly StrategyGalleryTemplate[];

export function findStrategyGalleryTemplate(templateId: string | null): StrategyGalleryTemplate | null {
  if (!templateId) return null;
  return STRATEGY_GALLERY_TEMPLATES.find((template) => template.id === templateId) ?? null;
}
