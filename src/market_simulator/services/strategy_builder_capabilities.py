from __future__ import annotations

DEFAULT_GUIDANCE_ACTIONS = [
    "Change tradable symbol",
    "Change benchmark",
    "Adjust stop loss",
    "Adjust take profit",
    "Adjust partial take profit",
    "Change allocation",
    "Change entry size",
    "Adjust max position",
    "Change transaction cost",
    "Change cooldown",
    "Adjust RSI thresholds",
    "Edit nested RSI settings",
    "Switch moving-average rules",
    "Edit nested moving-average windows",
    "Switch to SMA above",
    "Switch to MACD",
    "Switch to KD / stochastic",
    "Switch to seasonality by month",
    "Edit seasonality months",
    "Add / remove seasonality months",
    "Switch to relative strength",
    "Edit nested relative strength settings",
    "Switch to realized volatility",
    "Add MACD confirmation",
    "Add KD / stochastic confirmation",
    "Add relative strength confirmation",
    "Remove confirmation filters",
    "Use combined AND / OR rules",
    "Change group operator",
    "Change group conditions",
    "Use composite group conditions",
    "Remove group conditions",
    "Use any / all within N bars",
    "Change NOT inner rule",
    "Remove NOT wrapper",
    "Change window inner rule",
    "Remove window wrapper",
    "Use X then Y sequence rules",
    "Change window bars / mode",
    "Change sequence bars / steps",
    "Use composite sequence steps",
    "Remove sequence steps",
    "Adjust position management",
    "Change scale-in fraction",
    "Change max scale-in entries",
    "Change bars between adds",
    "Change minimum trade size",
    "Change exit behavior",
    "Remove scale-in policy",
    "Enable / disable core allocation",
    "Change capital",
    "Change dates",
    "Change rotation lookback",
    "Change rotation top N",
    "Change rotation fallback",
    "Add / remove rotation risk filter",
    "Change rotation rebalance",
]

SUPPORTED_STRATEGY_TYPES_MESSAGE = (
    "You can currently build ETF strategies using RSI mean reversion, SMA / moving-average crossover, "
    "SMA trend-state rules, MACD, KD / stochastic, relative strength, VIX and rates filters, "
    "yield-curve filters, realized volatility, seasonality, stop loss, take profit, cooldown, "
    "benchmark comparison, and core-overlay allocation."
)

UNSUPPORTED_EDIT_SUGGESTED_ACTION = (
    "You can ask me to change RSI thresholds, stop loss, take profit, cooldown, "
    "entry size, max position, benchmark, rotation lookback, top N, fallback, "
    "risk filter, MACD, KD/stochastic, seasonality, or relative strength."
)

UNSUPPORTED_EDIT_MESSAGE = (
    "I understood this as a requested strategy edit, but that edit type is not supported yet. "
    "You can ask me to change RSI thresholds, stop loss, take profit, cooldown, "
    "entry size, max position, benchmark, rotation lookback, top N, fallback, or risk filter."
)

NO_CHANGE_MESSAGE = (
    "I reviewed your request, but it did not change the current draft. "
    "You can ask for a specific edit like changing the tradable symbol, benchmark, stop loss, "
    "take profit, partial take profit, allocation, max position, transaction cost, cooldown, "
    "RSI thresholds, nested RSI edits, moving-average rules, nested moving-average window edits, "
    "switching to SMA above, switching to MACD, switching to KD/stochastic, "
    "switching to seasonality by month, editing seasonality months, "
    "switching to relative strength, editing nested relative strength settings, "
    "switching to realized volatility, "
    "adding or removing MACD/KD/relative strength confirmation filters, "
    "using combined AND/OR rules, changing group operator/conditions, using composite group conditions, "
    "using any/all within N bars, changing or removing the NOT wrapper, changing or removing the window wrapper, "
    "using X then Y sequence rules, changing window/sequence bars or window mode, "
    "changing sequence steps, using composite sequence steps, "
    "changing or removing sequence steps, position management, scale-in fraction, "
    "max scale-in entries, bars between adds, minimum trade size, sell-all or scale-out exit behavior, "
    "removing scale-in policy, core allocation, capital, or dates. Try prompts like "
    "'change RSI entry to 30', 'set stop loss to 8%', 'minimum trade size 1%', "
    "or 'sell all when RSI above 70'."
)
