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
    "Use any / all within N bars",
    "Use X then Y sequence rules",
    "Change capital",
    "Change dates",
]

SUPPORTED_STRATEGY_TYPES_MESSAGE = (
    "Right now the builder supports RSI mean reversion, moving-average crossover edits, "
    "MACD, KD/stochastic, seasonality by calendar month, relative strength versus another ETF, "
    "explicit combined entry/exit rules using AND/OR, temporal window rules using any/all within N bars, "
    "two-step sequence rules using X then Y within N bars, and add/remove confirmation filters "
    "for MACD, KD/stochastic, and relative strength on an existing draft. "
    "It also supports benchmark, stop loss, take profit, allocation, cooldown, capital, and date edits."
)

UNSUPPORTED_EDIT_SUGGESTED_ACTION = (
    "Try benchmark, stop loss, take profit, allocation, cooldown, RSI, moving averages, "
    "MACD, KD/stochastic, seasonality by month, relative strength, add/remove confirmation filters, "
    "combined AND/OR rules, any/all within N bars, X then Y sequence rules, capital, or dates."
)

UNSUPPORTED_EDIT_MESSAGE = (
    "I understood this as a requested strategy edit, but that edit type is not supported yet. "
    "Right now I can help with benchmark, stop loss, take profit, allocation, cooldown, "
    "RSI thresholds, moving-average rules, MACD, KD/stochastic, seasonality by month, "
    "relative strength, add/remove confirmation filters, combined AND/OR rules, "
    "any/all within N bars, X then Y sequence rules, capital, and dates."
)

NO_CHANGE_MESSAGE = (
    "I reviewed your request, but it did not change the current draft. "
    "You can ask for a specific edit like changing benchmark, stop loss, "
    "take profit, allocation, cooldown, RSI thresholds, moving-average rules, switching to MACD, "
    "switching to KD/stochastic, switching to seasonality by month, switching to relative strength, "
    "adding or removing MACD/KD/relative strength confirmation filters, "
    "using combined AND/OR rules, using any/all within N bars, using X then Y sequence rules, "
    "capital, or dates."
)