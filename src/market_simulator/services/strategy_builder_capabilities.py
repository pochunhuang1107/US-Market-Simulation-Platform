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
    "Switch moving-average rules",
    "Switch to MACD",
    "Switch to KD / stochastic",
    "Switch to seasonality by month",
    "Switch to relative strength",
    "Add MACD confirmation",
    "Add KD / stochastic confirmation",
    "Add relative strength confirmation",
    "Remove confirmation filters",
    "Use combined AND / OR rules",
    "Change group operator",
    "Change group conditions",
    "Remove group conditions",
    "Use any / all within N bars",
    "Change window inner rule",
    "Remove window wrapper",
    "Use X then Y sequence rules",
    "Change window bars / mode",
    "Change sequence bars / steps",
    "Remove sequence steps",
    "Adjust position management",
    "Enable / disable core allocation",
    "Change capital",
    "Change dates",
]

SUPPORTED_STRATEGY_TYPES_MESSAGE = (
    "Right now the builder supports RSI mean reversion, moving-average crossover edits, "
    "MACD, KD/stochastic, seasonality by calendar month, relative strength versus another ETF, "
    "tradable symbol changes on an existing draft, explicit combined entry/exit rules using AND/OR, "
    "direct edits for group operators and group conditions, direct removal of group conditions, "
    "temporal window rules using any/all within N bars, direct edits for window inner rules, "
    "direct removal of window wrappers, two-step sequence rules using X then Y within N bars, "
    "direct edits for window bars/modes and sequence bars/steps, direct removal of sequence steps, "
    "add/remove confirmation filters for MACD, KD/stochastic, and relative strength on an existing draft, "
    "partial take profit, position management, core allocation / core overlay, transaction cost, "
    "and max position percentage. "
    "It also supports benchmark, stop loss, take profit, allocation, cooldown, capital, and date edits."
)

UNSUPPORTED_EDIT_SUGGESTED_ACTION = (
    "Try changing the tradable symbol, benchmark, stop loss, take profit, partial take profit, "
    "allocation, max position, transaction cost, cooldown, RSI, moving averages, MACD, KD/stochastic, "
    "seasonality by month, relative strength, add/remove confirmation filters, combined AND/OR rules, "
    "group operator or condition edits, removing group conditions, any/all within N bars, "
    "window inner-rule edits, removing a window wrapper, X then Y sequence rules, "
    "window/sequence bars and modes, sequence step edits, removing sequence steps, "
    "position management, core allocation, capital, or dates."
)

UNSUPPORTED_EDIT_MESSAGE = (
    "I understood this as a requested strategy edit, but that edit type is not supported yet. "
    "Right now I can help with tradable symbol changes, benchmark, stop loss, take profit, "
    "partial take profit, allocation, max position, transaction cost, cooldown, RSI thresholds, "
    "moving-average rules, MACD, KD/stochastic, seasonality by month, relative strength, "
    "add/remove confirmation filters, combined AND/OR rules, group operator and condition edits, "
    "removing group conditions, any/all within N bars, window inner-rule edits, removing a window wrapper, "
    "X then Y sequence rules, window/sequence bars and modes, sequence step edits, "
    "removing sequence steps, position management, core allocation, capital, and dates."
)

NO_CHANGE_MESSAGE = (
    "I reviewed your request, but it did not change the current draft. "
    "You can ask for a specific edit like changing the tradable symbol, benchmark, stop loss, "
    "take profit, partial take profit, allocation, max position, transaction cost, cooldown, "
    "RSI thresholds, moving-average rules, switching to MACD, switching to KD/stochastic, "
    "switching to seasonality by month, switching to relative strength, "
    "adding or removing MACD/KD/relative strength confirmation filters, "
    "using combined AND/OR rules, changing or removing group operator/conditions, "
    "using any/all within N bars, changing or removing the window wrapper, using X then Y sequence rules, "
    "changing window/sequence bars or window mode, changing or removing sequence steps, "
    "position management, core allocation, capital, or dates."
)