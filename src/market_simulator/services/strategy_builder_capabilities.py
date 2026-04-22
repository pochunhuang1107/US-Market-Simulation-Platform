from __future__ import annotations

DEFAULT_GUIDANCE_ACTIONS = [
    "Change tradable symbol",
    "Change benchmark",
    "Adjust stop loss",
    "Adjust take profit",
    "Adjust partial take profit",
    "Change allocation",
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
    "Enable / disable core allocation",
    "Change capital",
    "Change dates",
]

SUPPORTED_STRATEGY_TYPES_MESSAGE = (
    "Right now the builder supports RSI mean reversion, nested RSI threshold/lookback edits on an existing draft, "
    "moving-average crossover edits, nested moving-average window edits on an existing draft, "
    "SMA-above trend-state rules, MACD, KD/stochastic, "
    "seasonality by calendar month, direct seasonality month edits on an existing draft, "
    "relative strength versus another ETF, nested relative strength edits on an existing draft, "
    "tradable symbol changes on an existing draft, explicit combined entry/exit rules using AND/OR, "
    "direct edits for group operators and group conditions, including composite replacements inside existing groups, "
    "direct removal of group conditions, temporal window rules using any/all within N bars, "
    "direct edits for NOT inner rules, direct removal of NOT wrappers, direct edits for window inner rules, "
    "direct removal of window wrappers, two-step sequence rules using X then Y within N bars, "
    "direct edits for window bars/modes and sequence bars/steps, including composite replacements inside existing sequences, "
    "direct removal of sequence steps, add/remove confirmation filters "
    "for MACD, KD/stochastic, and relative strength on an existing draft, "
    "partial take profit, position management, core allocation / core overlay, transaction cost, "
    "and max position percentage. "
    "It also supports benchmark, stop loss, take profit, allocation, cooldown, capital, and date edits."
)

UNSUPPORTED_EDIT_SUGGESTED_ACTION = (
    "Try changing the tradable symbol, benchmark, stop loss, take profit, partial take profit, "
    "allocation, max position, transaction cost, cooldown, RSI, nested RSI edits, moving averages, "
    "nested moving-average window edits, SMA above, MACD, KD/stochastic, seasonality by month, "
    "editing seasonality months, relative strength, nested relative strength edits, "
    "add/remove confirmation filters, combined AND/OR rules, group operator or condition edits, "
    "composite group-condition replacements, removing group conditions, any/all within N bars, "
    "NOT inner-rule edits, removing a NOT wrapper, window inner-rule edits, removing a window wrapper, "
    "X then Y sequence rules, window/sequence bars and modes, sequence step edits, "
    "composite sequence-step replacements, removing sequence steps, "
    "position management, core allocation, capital, or dates."
)

UNSUPPORTED_EDIT_MESSAGE = (
    "I understood this as a requested strategy edit, but that edit type is not supported yet. "
    "Right now I can help with tradable symbol changes, benchmark, stop loss, take profit, "
    "partial take profit, allocation, max position, transaction cost, cooldown, RSI thresholds, "
    "nested RSI edits, moving-average rules, nested moving-average window edits, SMA above, MACD, "
    "KD/stochastic, seasonality by month, editing seasonality months, relative strength, "
    "nested relative strength edits, add/remove confirmation filters, combined AND/OR rules, "
    "group operator and condition edits, composite group-condition replacements, removing group conditions, "
    "any/all within N bars, NOT inner-rule edits, removing a NOT wrapper, "
    "window inner-rule edits, removing a window wrapper, X then Y sequence rules, "
    "window/sequence bars and modes, sequence step edits, composite sequence-step replacements, "
    "removing sequence steps, position management, core allocation, capital, and dates."
)

NO_CHANGE_MESSAGE = (
    "I reviewed your request, but it did not change the current draft. "
    "You can ask for a specific edit like changing the tradable symbol, benchmark, stop loss, "
    "take profit, partial take profit, allocation, max position, transaction cost, cooldown, "
    "RSI thresholds, nested RSI edits, moving-average rules, nested moving-average window edits, "
    "switching to SMA above, switching to MACD, switching to KD/stochastic, "
    "switching to seasonality by month, editing seasonality months, "
    "switching to relative strength, editing nested relative strength settings, "
    "adding or removing MACD/KD/relative strength confirmation filters, "
    "using combined AND/OR rules, changing group operator/conditions, using composite group conditions, "
    "using any/all within N bars, changing or removing the NOT wrapper, changing or removing the window wrapper, "
    "using X then Y sequence rules, changing window/sequence bars or window mode, "
    "changing sequence steps, using composite sequence steps, "
    "changing or removing sequence steps, position management, core allocation, capital, or dates."
)