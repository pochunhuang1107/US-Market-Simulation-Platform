from market_simulator.services.strategy_builder_summary import _build_strategy_name, _describe_rule


def test_relative_return_summary_names_symbols_threshold_and_lookback():
    rule = {
        "kind": "atomic",
        "type": "relative_return_above",
        "symbol": "QQQ",
        "reference_symbol": "SPY",
        "lookback": 20,
        "threshold": 0.03,
    }

    assert (
        _describe_rule(rule)
        == "QQQ outperforms SPY by more than 3.0% over 20 trading days"
    )


def test_relative_return_summary_falls_back_to_tradable_symbol():
    rule = {
        "kind": "atomic",
        "type": "relative_return_above",
        "reference_symbol": "SPY",
        "lookback": 20,
        "threshold": 0.05,
    }

    assert (
        _describe_rule(rule, "QQQ")
        == "QQQ outperforms SPY by more than 5.0% over 20 trading days"
    )


def test_not_relative_return_summary_uses_no_longer_outperforms():
    rule = {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "relative_return_above",
            "symbol": "QQQ",
            "reference_symbol": "SPY",
            "lookback": 20,
            "threshold": 0.03,
        },
    }

    assert (
        _describe_rule(rule)
        == "QQQ no longer outperforms SPY by more than 3.0% over 20 trading days"
    )


def test_not_price_sma_summary_uses_no_longer_above_copy():
    rule = {
        "kind": "not",
        "rule": {
            "kind": "atomic",
            "type": "sma_above",
            "symbol": "SPY",
            "fast_window": 1,
            "slow_window": 200,
        },
    }

    assert _describe_rule(rule) == "SPY price is no longer above its 200-day SMA"


def test_reference_trend_filter_strategy_name_mentions_signal_and_filter_symbol():
    entry_rule = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "SPY",
                "fast_window": 1,
                "slow_window": 200,
            },
        ],
    }
    exit_rule = {
        "kind": "atomic",
        "type": "rsi_above",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 70,
    }

    assert _build_strategy_name("QQQ", entry_rule, exit_rule) == "qqq-rsi-with-spy-trend-filter"


def test_realized_volatility_summary_formats_percent_threshold():
    below_rule = {
        "kind": "atomic",
        "type": "realized_volatility_below",
        "symbol": "QQQ",
        "lookback": 20,
        "threshold": 0.25,
    }
    above_rule = {
        "kind": "atomic",
        "type": "realized_volatility_above",
        "symbol": "QQQ",
        "lookback": 20,
        "threshold": 0.35,
    }

    assert _describe_rule(below_rule) == "QQQ 20-day realized volatility is below 25.0%"
    assert _describe_rule(above_rule) == "QQQ 20-day realized volatility is above 35.0%"


def test_reference_series_summaries_use_readable_macro_labels():
    assert (
        _describe_rule(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "VIX",
                "threshold": 25,
            }
        )
        == "VIX is below 25"
    )
    assert (
        _describe_rule(
            {
                "kind": "atomic",
                "type": "series_below",
                "symbol": "DGS10",
                "threshold": 4.5,
            }
        )
        == "the 10-year Treasury yield is below 4.5%"
    )
    assert (
        _describe_rule(
            {
                "kind": "atomic",
                "type": "series_above",
                "symbol": "T10Y2Y",
                "threshold": 0,
            }
        )
        == "the 10Y-2Y Treasury spread is above 0"
    )


def test_daily_candle_summaries_are_readable():
    assert (
        _describe_rule({"kind": "atomic", "type": "bullish_candle", "symbol": "QQQ"})
        == "QQQ closes above its open"
    )
    assert (
        _describe_rule({"kind": "atomic", "type": "bearish_candle", "symbol": "QQQ"})
        == "QQQ closes below its open"
    )
    assert (
        _describe_rule({"kind": "atomic", "type": "close_above_previous_high", "symbol": "QQQ"})
        == "QQQ closes above the previous day's high"
    )
    assert (
        _describe_rule({"kind": "atomic", "type": "close_below_previous_low", "symbol": "QQQ"})
        == "QQQ closes below the previous day's low"
    )
    assert (
        _describe_rule({"kind": "atomic", "type": "close_near_high", "symbol": "QQQ"})
        == "QQQ closes in the top 20% of the day's range"
    )
    assert (
        _describe_rule(
            {"kind": "atomic", "type": "close_near_high", "symbol": "QQQ", "threshold": 0.1}
        )
        == "QQQ closes in the top 10% of the day's range"
    )
    assert (
        _describe_rule(
            {"kind": "atomic", "type": "close_near_low", "symbol": "QQQ", "threshold": 0.15}
        )
        == "QQQ closes in the bottom 15% of the day's range"
    )


def test_existing_indicator_and_composite_summaries_still_work():
    group = {
        "kind": "group",
        "operator": "AND",
        "rules": [
            {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            {
                "kind": "atomic",
                "type": "sma_above",
                "symbol": "QQQ",
                "fast_window": 1,
                "slow_window": 200,
            },
            {
                "kind": "atomic",
                "type": "macd_bullish_cross",
                "symbol": "QQQ",
            },
            {
                "kind": "atomic",
                "type": "kd_golden_cross",
                "symbol": "QQQ",
            },
        ],
    }

    assert _describe_rule(group) == (
        "QQQ RSI(14) is below 30 and "
        "QQQ price is above its 200-day SMA and "
        "QQQ MACD turns bullish and "
        "QQQ KD/stochastic turns bullish"
    )
