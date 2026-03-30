from __future__ import annotations

import pandas as pd

from market_simulator.models.strategy_v2 import (
    AtomicRule,
    GroupRule,
    NotRule,
    RuleNode,
    SequenceRule,
    WindowRule,
)


def _eval_atomic(rule: AtomicRule, bundle, index: int) -> bool:
    df = bundle.tradable

    if rule.type == "rsi_below":
        col = f"rsi_{rule.lookback}"
        return bool(pd.notna(df.iloc[index][col]) and df.iloc[index][col] < rule.threshold)

    elif rule.type == "rsi_above":
        col = f"rsi_{rule.lookback}"
        return bool(pd.notna(df.iloc[index][col]) and df.iloc[index][col] > rule.threshold)

    elif rule.type == "sma_cross_above":
        fast_col = f"sma_{rule.fast_window}"
        slow_col = f"sma_{rule.slow_window}"
        if index == 0:
            return False

        fast_prev = df.iloc[index - 1][fast_col]
        slow_prev = df.iloc[index - 1][slow_col]
        fast_now = df.iloc[index][fast_col]
        slow_now = df.iloc[index][slow_col]

        if pd.isna(fast_prev) or pd.isna(slow_prev) or pd.isna(fast_now) or pd.isna(slow_now):
            return False

        return bool(fast_prev <= slow_prev and fast_now > slow_now)

    elif rule.type == "sma_cross_below":
        fast_col = f"sma_{rule.fast_window}"
        slow_col = f"sma_{rule.slow_window}"
        if index == 0:
            return False

        fast_prev = df.iloc[index - 1][fast_col]
        slow_prev = df.iloc[index - 1][slow_col]
        fast_now = df.iloc[index][fast_col]
        slow_now = df.iloc[index][slow_col]

        if pd.isna(fast_prev) or pd.isna(slow_prev) or pd.isna(fast_now) or pd.isna(slow_now):
            return False

        return bool(fast_prev >= slow_prev and fast_now < slow_now)

    elif rule.type == "sma_above":
        fast_col = f"sma_{rule.fast_window}"
        slow_col = f"sma_{rule.slow_window}"

        fast_now = df.iloc[index][fast_col]
        slow_now = df.iloc[index][slow_col]

        if pd.isna(fast_now) or pd.isna(slow_now):
            return False

        return bool(fast_now > slow_now)

    elif rule.type == "macd_bullish_cross":
        if index == 0:
            return False

        macd_prev = df.iloc[index - 1]["macd"]
        signal_prev = df.iloc[index - 1]["macd_signal"]
        macd_now = df.iloc[index]["macd"]
        signal_now = df.iloc[index]["macd_signal"]

        if pd.isna(macd_prev) or pd.isna(signal_prev) or pd.isna(macd_now) or pd.isna(signal_now):
            return False

        return bool(macd_prev <= signal_prev and macd_now > signal_now)

    elif rule.type == "macd_bearish_cross":
        if index == 0:
            return False

        macd_prev = df.iloc[index - 1]["macd"]
        signal_prev = df.iloc[index - 1]["macd_signal"]
        macd_now = df.iloc[index]["macd"]
        signal_now = df.iloc[index]["macd_signal"]

        if pd.isna(macd_prev) or pd.isna(signal_prev) or pd.isna(macd_now) or pd.isna(signal_now):
            return False

        return bool(macd_prev >= signal_prev and macd_now < signal_now)

    elif rule.type == "kd_golden_cross":
        if index == 0:
            return False

        k_prev = df.iloc[index - 1]["k"]
        d_prev = df.iloc[index - 1]["d"]
        k_now = df.iloc[index]["k"]
        d_now = df.iloc[index]["d"]

        if pd.isna(k_prev) or pd.isna(d_prev) or pd.isna(k_now) or pd.isna(d_now):
            return False

        return bool(k_prev <= d_prev and k_now > d_now)

    elif rule.type == "kd_dead_cross":
        if index == 0:
            return False

        k_prev = df.iloc[index - 1]["k"]
        d_prev = df.iloc[index - 1]["d"]
        k_now = df.iloc[index]["k"]
        d_now = df.iloc[index]["d"]

        if pd.isna(k_prev) or pd.isna(d_prev) or pd.isna(k_now) or pd.isna(d_now):
            return False

        return bool(k_prev >= d_prev and k_now < d_now)

    elif rule.type == "month_in":
        dt = pd.Timestamp(df.iloc[index]["date"])
        return bool(dt.month in (rule.month_values or []))

    elif rule.type == "relative_return_above":
        col = f"return_{rule.lookback}"
        return bool(pd.notna(df.iloc[index][col]) and df.iloc[index][col] > rule.threshold)

    else:
        raise ValueError(f"Unsupported atomic rule type: {rule.type}")


def evaluate_rule(rule: RuleNode, bundle, index: int) -> bool:
    if isinstance(rule, AtomicRule):
        return _eval_atomic(rule, bundle, index)

    elif isinstance(rule, NotRule):
        return not evaluate_rule(rule.rule, bundle, index)

    elif isinstance(rule, GroupRule):
        vals = [evaluate_rule(r, bundle, index) for r in rule.rules]
        if rule.operator == "AND":
            return all(vals)
        elif rule.operator == "OR":
            return any(vals)
        else:
            raise ValueError(f"Unsupported group operator: {rule.operator}")

    elif isinstance(rule, WindowRule):
        start = max(0, index - rule.window_bars + 1)
        vals = [evaluate_rule(rule.rule, bundle, i) for i in range(start, index + 1)]
        if rule.mode == "ANY":
            return any(vals)
        elif rule.mode == "ALL":
            return all(vals)
        else:
            raise ValueError(f"Unsupported window mode: {rule.mode}")

    elif isinstance(rule, SequenceRule):
        cursor = max(0, index - rule.window_bars + 1)

        for step in rule.steps:
            found = False
            for i in range(cursor, index + 1):
                if evaluate_rule(step, bundle, i):
                    cursor = i + 1
                    found = True
                    break
            if not found:
                return False

        return True

    else:
        raise ValueError(f"Unsupported rule node type: {type(rule)}")