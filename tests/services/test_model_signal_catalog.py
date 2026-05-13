from __future__ import annotations

import pytest

from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.services.model_signal_catalog import (
    ModelSignalCatalogError,
    build_model_signal_strategy_config,
    get_model_signal_catalog_entry,
    list_model_signal_catalog,
)


MODEL_VERSION = "linear_smooth10_margin002_v1"


def test_catalog_registers_linear_smooth10_model() -> None:
    entry = get_model_signal_catalog_entry(MODEL_VERSION)

    assert entry is not None
    assert entry.display_name == "Linear Smooth 10 Margin 0.002"
    assert entry.research_status == "paper_tracking"
    assert entry.ranking_field == "score"
    assert entry.default_top_n == 1
    assert entry.default_signal_bucket_filter == ("top",)
    assert entry.default_fallback.type == "cash"
    assert entry.label_horizon_days == 20
    assert entry.feature_set_version == "default_features_v1"
    assert "XLE, IBIT, ARKK, SLV, and QQQ" in " ".join(entry.risk_notes)


def test_catalog_lists_only_enabled_models_by_default() -> None:
    entries = list_model_signal_catalog()

    assert [entry.model_version for entry in entries] == [MODEL_VERSION]


def test_strategy_config_helper_builds_valid_model_signal_strategy_v2_config() -> None:
    config = build_model_signal_strategy_config(
        model_version=MODEL_VERSION,
        start_date="2025-01-02",
        end_date="2026-05-08",
    )

    strategy = StrategyV2.model_validate(config)

    assert strategy.model_signal is not None
    assert strategy.model_signal.enabled is True
    assert strategy.model_signal.model_version == MODEL_VERSION
    assert strategy.model_signal.ranking_field == "score"
    assert strategy.model_signal.top_n == 1
    assert strategy.model_signal.signal_bucket_filter == ["top"]
    assert strategy.model_signal.fallback.type == "cash"
    assert strategy.benchmark_symbol == "SPY"


def test_strategy_config_helper_allows_valid_overrides() -> None:
    config = build_model_signal_strategy_config(
        model_version=MODEL_VERSION,
        start_date="2025-01-02",
        end_date="2026-05-08",
        universe=["qqq", "spy", "tlt"],
        top_n=2,
        fallback={"type": "asset", "symbol": "tlt"},
        benchmark="QQQ",
        signal_bucket_filter="top",
        min_confidence=0.5,
    )

    model_signal = StrategyV2.model_validate(config).model_signal

    assert model_signal is not None
    assert model_signal.universe == ["QQQ", "SPY", "TLT"]
    assert model_signal.top_n == 2
    assert model_signal.fallback.type == "asset"
    assert model_signal.fallback.symbol == "TLT"
    assert model_signal.min_confidence == 0.5


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"universe": ["AAPL"]}, "unsupported by this model"),
        ({"universe": ["QQQ"], "top_n": 2}, "top_n cannot exceed"),
        ({"top_n": 0}, "top_n must be at least 1"),
        ({"fallback": {"type": "asset", "symbol": "AAPL"}}, "fallback symbol is not supported"),
        ({"benchmark": "AAPL"}, "benchmark symbol is not supported"),
        ({"ranking_field": "predicted_return"}, "ranking_field is not allowed"),
    ],
)
def test_strategy_config_helper_rejects_invalid_inputs(kwargs, message: str) -> None:
    with pytest.raises(ModelSignalCatalogError, match=message):
        build_model_signal_strategy_config(
            model_version=MODEL_VERSION,
            start_date="2025-01-02",
            end_date="2026-05-08",
            **kwargs,
        )


def test_strategy_config_helper_rejects_unknown_model() -> None:
    with pytest.raises(ModelSignalCatalogError, match="not registered or enabled"):
        build_model_signal_strategy_config(
            model_version="unknown_model_v0",
            start_date="2025-01-02",
            end_date="2026-05-08",
        )
