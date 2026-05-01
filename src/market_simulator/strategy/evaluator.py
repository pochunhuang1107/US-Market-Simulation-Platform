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
from market_simulator.strategy.dataframe_resolution import (
    infer_tradable_symbol,
    resolve_market_dataframe,
    row_position_for_date,
    tradable_row_date,
)


def _rule_row(rule: AtomicRule, bundle, index: int, tradable_symbol: str | None):
    df = resolve_market_dataframe(bundle, rule.symbol, tradable_symbol)
    date = tradable_row_date(bundle, index)
    row_pos = row_position_for_date(df, date)
    if row_pos is None:
        return df, None
    return df, row_pos


def _return_at(df: pd.DataFrame, row_pos: int, lookback: int | None):
    if lookback is None:
        return pd.NA

    col = f"return_{lookback}"
    if col in df.columns:
        return df.iloc[row_pos][col]

    lookback_pos = row_pos - lookback
    if lookback_pos < 0:
        return pd.NA

    prior_close = df.iloc[lookback_pos]["close"]
    close = df.iloc[row_pos]["close"]
    if pd.isna(prior_close) or pd.isna(close) or float(prior_close) == 0:
        return pd.NA

    return float(close) / float(prior_close) - 1.0


def _eval_relative_return_above(
    rule: AtomicRule,
    bundle,
    index: int,
    tradable_symbol: str | None,
) -> bool:
    date = tradable_row_date(bundle, index)
    primary_symbol = rule.symbol or tradable_symbol
    primary_df = resolve_market_dataframe(bundle, primary_symbol, tradable_symbol)
    reference_df = resolve_market_dataframe(bundle, rule.reference_symbol, tradable_symbol)

    primary_pos = row_position_for_date(primary_df, date)
    reference_pos = row_position_for_date(reference_df, date)
    if primary_pos is None or reference_pos is None:
        return False

    primary_return = _return_at(primary_df, primary_pos, rule.lookback)
    reference_return = _return_at(reference_df, reference_pos, rule.lookback)
    if pd.isna(primary_return) or pd.isna(reference_return):
        return False

    return bool(float(primary_return) - float(reference_return) > float(rule.threshold))


def _eval_atomic(rule: AtomicRule, bundle, index: int, tradable_symbol: str | None) -> bool:
    if rule.type == "relative_return_above":
        return _eval_relative_return_above(rule, bundle, index, tradable_symbol)

    df, row_pos = _rule_row(rule, bundle, index, tradable_symbol)
    if row_pos is None:
        return False

    if rule.type == "rsi_below":
        col = f"rsi_{rule.lookback}"
        return bool(pd.notna(df.iloc[row_pos][col]) and df.iloc[row_pos][col] < rule.threshold)

    elif rule.type == "rsi_above":
        col = f"rsi_{rule.lookback}"
        return bool(pd.notna(df.iloc[row_pos][col]) and df.iloc[row_pos][col] > rule.threshold)

    elif rule.type == "realized_volatility_below":
        col = f"realized_volatility_{rule.lookback}"
        if col not in df.columns:
            return False
        value = df.iloc[row_pos][col]
        return bool(pd.notna(value) and value < rule.threshold)

    elif rule.type == "realized_volatility_above":
        col = f"realized_volatility_{rule.lookback}"
        if col not in df.columns:
            return False
        value = df.iloc[row_pos][col]
        return bool(pd.notna(value) and value > rule.threshold)

    elif rule.type == "sma_cross_above":
        fast_col = f"sma_{rule.fast_window}"
        slow_col = f"sma_{rule.slow_window}"
        if row_pos == 0:
            return False

        fast_prev = df.iloc[row_pos - 1][fast_col]
        slow_prev = df.iloc[row_pos - 1][slow_col]
        fast_now = df.iloc[row_pos][fast_col]
        slow_now = df.iloc[row_pos][slow_col]

        if pd.isna(fast_prev) or pd.isna(slow_prev) or pd.isna(fast_now) or pd.isna(slow_now):
            return False

        return bool(fast_prev <= slow_prev and fast_now > slow_now)

    elif rule.type == "sma_cross_below":
        fast_col = f"sma_{rule.fast_window}"
        slow_col = f"sma_{rule.slow_window}"
        if row_pos == 0:
            return False

        fast_prev = df.iloc[row_pos - 1][fast_col]
        slow_prev = df.iloc[row_pos - 1][slow_col]
        fast_now = df.iloc[row_pos][fast_col]
        slow_now = df.iloc[row_pos][slow_col]

        if pd.isna(fast_prev) or pd.isna(slow_prev) or pd.isna(fast_now) or pd.isna(slow_now):
            return False

        return bool(fast_prev >= slow_prev and fast_now < slow_now)

    elif rule.type == "sma_above":
        fast_col = f"sma_{rule.fast_window}"
        slow_col = f"sma_{rule.slow_window}"

        fast_now = df.iloc[row_pos][fast_col]
        slow_now = df.iloc[row_pos][slow_col]

        if pd.isna(fast_now) or pd.isna(slow_now):
            return False

        return bool(fast_now > slow_now)

    elif rule.type == "macd_bullish_cross":
        if row_pos == 0:
            return False

        macd_prev = df.iloc[row_pos - 1]["macd"]
        signal_prev = df.iloc[row_pos - 1]["macd_signal"]
        macd_now = df.iloc[row_pos]["macd"]
        signal_now = df.iloc[row_pos]["macd_signal"]

        if pd.isna(macd_prev) or pd.isna(signal_prev) or pd.isna(macd_now) or pd.isna(signal_now):
            return False

        return bool(macd_prev <= signal_prev and macd_now > signal_now)

    elif rule.type == "macd_bearish_cross":
        if row_pos == 0:
            return False

        macd_prev = df.iloc[row_pos - 1]["macd"]
        signal_prev = df.iloc[row_pos - 1]["macd_signal"]
        macd_now = df.iloc[row_pos]["macd"]
        signal_now = df.iloc[row_pos]["macd_signal"]

        if pd.isna(macd_prev) or pd.isna(signal_prev) or pd.isna(macd_now) or pd.isna(signal_now):
            return False

        return bool(macd_prev >= signal_prev and macd_now < signal_now)

    elif rule.type == "kd_golden_cross":
        if row_pos == 0:
            return False

        k_prev = df.iloc[row_pos - 1]["k"]
        d_prev = df.iloc[row_pos - 1]["d"]
        k_now = df.iloc[row_pos]["k"]
        d_now = df.iloc[row_pos]["d"]

        if pd.isna(k_prev) or pd.isna(d_prev) or pd.isna(k_now) or pd.isna(d_now):
            return False

        return bool(k_prev <= d_prev and k_now > d_now)

    elif rule.type == "kd_dead_cross":
        if row_pos == 0:
            return False

        k_prev = df.iloc[row_pos - 1]["k"]
        d_prev = df.iloc[row_pos - 1]["d"]
        k_now = df.iloc[row_pos]["k"]
        d_now = df.iloc[row_pos]["d"]

        if pd.isna(k_prev) or pd.isna(d_prev) or pd.isna(k_now) or pd.isna(d_now):
            return False

        return bool(k_prev >= d_prev and k_now < d_now)

    elif rule.type == "month_in":
        dt = pd.Timestamp(df.iloc[row_pos]["date"])
        return bool(dt.month in (rule.month_values or []))

    else:
        raise ValueError(f"Unsupported atomic rule type: {rule.type}")


def evaluate_rule(rule: RuleNode, bundle, index: int, tradable_symbol: str | None = None) -> bool:
    tradable_symbol = tradable_symbol or infer_tradable_symbol(bundle)

    if isinstance(rule, AtomicRule):
        return _eval_atomic(rule, bundle, index, tradable_symbol)

    elif isinstance(rule, NotRule):
        return not evaluate_rule(rule.rule, bundle, index, tradable_symbol)

    elif isinstance(rule, GroupRule):
        vals = [evaluate_rule(r, bundle, index, tradable_symbol) for r in rule.rules]
        if rule.operator == "AND":
            return all(vals)
        elif rule.operator == "OR":
            return any(vals)
        else:
            raise ValueError(f"Unsupported group operator: {rule.operator}")

    elif isinstance(rule, WindowRule):
        start = max(0, index - rule.window_bars + 1)
        vals = [evaluate_rule(rule.rule, bundle, i, tradable_symbol) for i in range(start, index + 1)]
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
                if evaluate_rule(step, bundle, i, tradable_symbol):
                    cursor = i + 1
                    found = True
                    break
            if not found:
                return False

        return True

    else:
        raise ValueError(f"Unsupported rule node type: {type(rule)}")
