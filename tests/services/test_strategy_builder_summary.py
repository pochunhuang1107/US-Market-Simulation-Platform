from market_simulator.services.strategy_builder_summary import _describe_rule


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
