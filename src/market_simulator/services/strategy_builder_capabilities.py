from __future__ import annotations

DEFAULT_GUIDANCE_ACTIONS = [
    "Change benchmark",
    "Adjust stop loss",
    "Adjust take profit",
    "Change allocation",
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
    "Use any / all within N bars",
    "Change window inner rule",
    "Use X then Y sequence rules",
    "Change window bars / mode",
    "Change sequence bars / steps",
    "Change capital",
    "Change dates",
]

SUPPORTED_STRATEGY_TYPES_MESSAGE = (
    "Right now the builder supports RSI mean reversion, moving-average crossover edits, "
    "MACD, KD/stochastic, seasonality by calendar month, relative strength versus another ETF, "
    "explicit combined entry/exit rules using AND/OR, direct edits for group operators and group conditions, "
    "temporal window rules using any/all within N bars, direct edits for window inner rules, "
    "two-step sequence rules using X then Y within N bars, add/remove confirmation filters "
    "for MACD, KD/stochastic, and relative strength on an existing draft, and direct edits for "
    "window bars/modes and sequence bars/steps. "
    "It also supports benchmark, stop loss, take profit, allocation, cooldown, capital, and date edits."
)

UNSUPPORTED_EDIT_SUGGESTED_ACTION = (
    "Try benchmark, stop loss, take profit, allocation, cooldown, RSI, moving averages, "
    "MACD, KD/stochastic, seasonality by month, relative strength, add/remove confirmation filters, "
    "combined AND/OR rules, group operator or condition edits, any/all within N bars, window inner-rule edits, "
    "X then Y sequence rules, window/sequence bars and modes, sequence step edits, capital, or dates."
)

UNSUPPORTED_EDIT_MESSAGE = (
    "I understood this as a requested strategy edit, but that edit type is not supported yet. "
    "Right now I can help with benchmark, stop loss, take profit, allocation, cooldown, "
    "RSI thresholds, moving-average rules, MACD, KD/stochastic, seasonality by month, "
    "relative strength, add/remove confirmation filters, combined AND/OR rules, "
    "group operator and condition edits, any/all within N bars, window inner-rule edits, "
    "X then Y sequence rules, window/sequence bars and modes, sequence step edits, "
    "capital, and dates."
)

NO_CHANGE_MESSAGE = (
    "I reviewed your request, but it did not change the current draft. "
    "You can ask for a specific edit like changing benchmark, stop loss, "
    "take profit, allocation, cooldown, RSI thresholds, moving-average rules, switching to MACD, "
    "switching to KD/stochastic, switching to seasonality by month, switching to relative strength, "
    "adding or removing MACD/KD/relative strength confirmation filters, "
    "using combined AND/OR rules, changing group operator or conditions, "
    "using any/all within N bars, changing the window inner rule, using X then Y sequence rules, "
    "changing window/sequence bars or window mode, changing sequence steps, capital, or dates."
)