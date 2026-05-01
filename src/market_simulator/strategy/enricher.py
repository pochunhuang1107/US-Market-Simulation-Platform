from __future__ import annotations

from market_simulator.data.repository import MarketDataBundle
from market_simulator.indicators import (
    compute_kd,
    compute_macd,
    compute_realized_volatility,
    compute_rsi,
    compute_sma,
)
from market_simulator.models.strategy_v2 import AtomicRule, GroupRule, NotRule, SequenceRule, WindowRule
from market_simulator.strategy.dataframe_resolution import resolve_market_data_target


def _collect(rule, out):
    if isinstance(rule, AtomicRule):
        out.append(rule)
    elif isinstance(rule, NotRule):
        _collect(rule.rule, out)
    elif isinstance(rule, WindowRule):
        _collect(rule.rule, out)
    elif isinstance(rule, SequenceRule):
        for step in rule.steps:
            _collect(step, out)
    elif isinstance(rule, GroupRule):
        for child in rule.rules:
            _collect(child, out)


def _ensure(df, rule):
    if rule.type in {"rsi_below", "rsi_above"}:
        col = f"rsi_{rule.lookback}"
        if col not in df.columns:
            df[col] = compute_rsi(df["close"], rule.lookback)

    elif rule.type in {"sma_cross_above", "sma_cross_below", "sma_above"}:
        f = f"sma_{rule.fast_window}"
        s = f"sma_{rule.slow_window}"
        if f not in df.columns:
            df[f] = compute_sma(df["close"], rule.fast_window)
        if s not in df.columns:
            df[s] = compute_sma(df["close"], rule.slow_window)

    elif rule.type in {"macd_bullish_cross", "macd_bearish_cross"}:
        if "macd" not in df.columns or "macd_signal" not in df.columns or "macd_hist" not in df.columns:
            macd = compute_macd(df["close"])
            df["macd"] = macd["macd"]
            df["macd_signal"] = macd["macd_signal"]
            df["macd_hist"] = macd["macd_hist"]

    elif rule.type in {"kd_golden_cross", "kd_dead_cross"}:
        if "k" not in df.columns or "d" not in df.columns:
            kd = compute_kd(df["high"], df["low"], df["close"])
            df["k"] = kd["k"]
            df["d"] = kd["d"]

    elif rule.type == "relative_return_above":
        col = f"return_{rule.lookback}"
        if col not in df.columns:
            df[col] = df["close"] / df["close"].shift(rule.lookback) - 1.0

    elif rule.type in {"realized_volatility_below", "realized_volatility_above"}:
        col = f"realized_volatility_{rule.lookback}"
        if col not in df.columns:
            df[col] = compute_realized_volatility(df["close"], rule.lookback)

    return df


def enrich_market_data(bundle: MarketDataBundle, strategy):
    tradable = bundle.tradable.copy()
    refs = {k: v.copy() for k, v in bundle.references.items()}
    working_bundle = MarketDataBundle(tradable=tradable, references=refs)

    rules = []
    _collect(strategy.entry_rule, rules)
    _collect(strategy.exit_rule, rules)

    for rule in rules:
        target_key, _ = resolve_market_data_target(
            working_bundle,
            rule.symbol,
            strategy.tradable_symbol,
        )
        if target_key is None:
            tradable = _ensure(tradable, rule)
            working_bundle.tradable = tradable
        else:
            refs[target_key] = _ensure(refs[target_key], rule)
            working_bundle.references = refs

        if rule.type == "relative_return_above":
            reference_key, _ = resolve_market_data_target(
                working_bundle,
                rule.reference_symbol,
                strategy.tradable_symbol,
            )
            if reference_key is None:
                tradable = _ensure(tradable, rule)
                working_bundle.tradable = tradable
            else:
                refs[reference_key] = _ensure(refs[reference_key], rule)
                working_bundle.references = refs

    return MarketDataBundle(tradable=tradable, references=refs)
