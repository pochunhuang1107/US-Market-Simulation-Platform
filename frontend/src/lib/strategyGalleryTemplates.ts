type StrategyStyle = 'Mean reversion' | 'Trend' | 'Risk filter' | 'Overlay' | 'Relative strength';
type RiskLevel = 'Lower' | 'Moderate' | 'Higher';

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
  scale_out_fraction: number;
  profit_reduce_threshold?: number | null;
  max_scale_in_steps?: number | null;
  min_bars_between_scale_ins?: number;
  scale_in_requires_persistent_signal?: boolean;
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
  style: StrategyStyle;
  riskLevel: RiskLevel;
  expectedBehavior: string;
  entryRuleText: string;
  exitRuleText: string;
  riskControls: string[];
  config: StrategyV2TemplateConfig;
};

const TEMPLATE_BACKTEST_YEARS = 5;
const TEMPLATE_BACKTEST_SAFETY_DAYS = 3;

function toIsoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function shiftUtcDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

function shiftUtcYears(value: Date, years: number): Date {
  const next = new Date(value);
  next.setUTCFullYear(next.getUTCFullYear() + years);
  return next;
}

function rollBackToWeekday(value: Date): Date {
  const next = new Date(value);
  const day = next.getUTCDay();
  if (day === 0) return shiftUtcDays(next, -2);
  if (day === 6) return shiftUtcDays(next, -1);
  return next;
}

function rollForwardToWeekday(value: Date): Date {
  const next = new Date(value);
  const day = next.getUTCDay();
  if (day === 0) return shiftUtcDays(next, 1);
  if (day === 6) return shiftUtcDays(next, 2);
  return next;
}

function getDefaultTemplateDateRange(today = new Date()) {
  const latestSupportedEnd = rollBackToWeekday(today);
  const approximateStart = shiftUtcDays(
    shiftUtcYears(latestSupportedEnd, -TEMPLATE_BACKTEST_YEARS),
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

export const STRATEGY_GALLERY_TEMPLATES = [
  {
    id: 'qqq-rsi-mean-reversion',
    title: 'QQQ RSI Mean Reversion',
    shortExplanation: 'Tests whether QQQ pullbacks can be entered after short-term oversold RSI readings.',
    symbols: ['QQQ'],
    style: 'Mean reversion',
    riskLevel: 'Moderate',
    expectedBehavior: 'Starts with 25% position, adds only after the RSI signal persists and the spacing rule allows, and caps scale-in steps.',
    entryRuleText: 'Enter QQQ when RSI(14) falls below 35.',
    exitRuleText: 'Exit when RSI(14) rises above 65.',
    riskControls: ['10% stop loss', 'Starts with 25% position', 'Adds only after signal persists and spacing rule allows', 'Caps scale-in steps', '5 bps transaction cost'],
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
        scale_out_fraction: 0.5,
        profit_reduce_threshold: null,
        max_scale_in_steps: 4,
        min_bars_between_scale_ins: 3,
        scale_in_requires_persistent_signal: true
      }
    }
  },
  {
    id: 'qqq-vix-risk-on-risk-off',
    title: 'QQQ VIX Risk-On/Risk-Off',
    shortExplanation: 'Tests whether QQQ entries should require calmer VIX conditions plus an RSI pullback.',
    symbols: ['QQQ', 'VIX'],
    style: 'Risk filter',
    riskLevel: 'Moderate',
    expectedBehavior: 'May reduce exposure when volatility is elevated, while still looking for QQQ pullbacks.',
    entryRuleText: 'Enter when VIX is below 25 and QQQ RSI(14) is below 40.',
    exitRuleText: 'Exit when VIX rises above 35 or QQQ RSI(14) rises above 70.',
    riskControls: ['10% stop loss', 'VIX regime filter', '5 bps transaction cost'],
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
      }
    }
  },
  {
    id: 'qqq-core-vix-overlay',
    title: 'QQQ Core + VIX Tactical Overlay',
    shortExplanation: 'Tests a QQQ core position with tactical overlay exposure controlled by VIX thresholds.',
    symbols: ['QQQ', 'VIX'],
    style: 'Overlay',
    riskLevel: 'Moderate',
    expectedBehavior: 'Designed to keep a core allocation while adding overlay exposure when VIX is calmer.',
    entryRuleText: 'Keep a 60% QQQ core. Add overlay exposure when VIX is below 15.',
    exitRuleText: 'Reduce overlay exposure when VIX is above 35.',
    riskControls: ['60% core allocation', 'Tactical overlay exits on high VIX', '5 bps transaction cost'],
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
      }
    }
  },
  {
    id: 'spy-moving-average-trend-filter',
    title: 'SPY Moving Average Trend Filter',
    shortExplanation: 'Tests whether SPY exposure should only be active while price remains above its 200-day average.',
    symbols: ['SPY'],
    style: 'Trend',
    riskLevel: 'Lower',
    expectedBehavior: 'Designed to participate in broad uptrends and move to cash after trend breaks.',
    entryRuleText: 'Enter SPY when price is above its 200-day SMA.',
    exitRuleText: 'Exit when price crosses below its 200-day SMA.',
    riskControls: ['Trend-state filter', '10% stop loss', '5 bps transaction cost'],
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
      }
    }
  },
  {
    id: 'xlk-sector-relative-strength',
    title: 'XLK Sector Relative Strength',
    shortExplanation: 'Tests a supported sector-style idea by trading XLK only when it leads SPY over a 60-day window.',
    symbols: ['XLK', 'SPY'],
    style: 'Relative strength',
    riskLevel: 'Higher',
    expectedBehavior: 'Designed to focus on technology-sector strength, not rotate among every sector yet.',
    entryRuleText: 'Enter XLK when XLK outperforms SPY by more than 3% over 60 trading days.',
    exitRuleText: 'Exit when XLK no longer outperforms SPY by more than 3% over 60 trading days.',
    riskControls: ['Relative strength confirmation', '10% stop loss', '5 bps transaction cost'],
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
      }
    }
  },
  {
    id: 'qqq-tlt-defensive-relative-strength',
    title: 'QQQ / TLT Defensive Relative Strength',
    shortExplanation: 'Tests staying in QQQ only when it leads long-duration Treasuries over a medium-term window.',
    symbols: ['QQQ', 'TLT'],
    style: 'Risk filter',
    riskLevel: 'Higher',
    expectedBehavior: 'May step out of QQQ when defensive TLT strength is comparatively stronger.',
    entryRuleText: 'Enter QQQ when QQQ outperforms TLT over 60 trading days.',
    exitRuleText: 'Exit when QQQ no longer outperforms TLT over 60 trading days.',
    riskControls: ['Defensive relative strength filter', '10% stop loss', '5 bps transaction cost'],
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
      }
    }
  }
] as const satisfies readonly StrategyGalleryTemplate[];

export function findStrategyGalleryTemplate(templateId: string | null): StrategyGalleryTemplate | null {
  if (!templateId) return null;
  return STRATEGY_GALLERY_TEMPLATES.find((template) => template.id === templateId) ?? null;
}
