from __future__ import annotations

from market_simulator.settings import (
    DEFAULT_SUPPORTED_REFERENCE_SERIES_SYMBOLS,
    Settings,
)


INTENDED_REFERENCE_SERIES_SYMBOLS = {
    "VIX",
    "VIX9D",
    "VXEEM",
    "DGS10",
    "DGS2",
    "T10Y2Y",
    "DFF",
}


def test_default_supported_reference_series_symbols_are_exactly_intended() -> None:
    configured_symbols = {
        symbol.strip().upper()
        for symbol in DEFAULT_SUPPORTED_REFERENCE_SERIES_SYMBOLS.split(",")
        if symbol.strip()
    }
    settings = Settings(
        supported_reference_series_symbols_csv=DEFAULT_SUPPORTED_REFERENCE_SERIES_SYMBOLS
    )

    assert configured_symbols == INTENDED_REFERENCE_SERIES_SYMBOLS
    assert set(settings.supported_reference_series_symbols) == INTENDED_REFERENCE_SERIES_SYMBOLS


def test_supported_reference_series_symbols_normalize_and_dedupe_overrides() -> None:
    settings = Settings(
        supported_reference_series_symbols_csv=" vix, DGS10, vix, dff ,, "
    )

    assert settings.supported_reference_series_symbols == ("DFF", "DGS10", "VIX")


def test_runtime_data_paths_stay_within_curated_boundaries() -> None:
    settings = Settings(
        market_data_path="s3://bucket/curated/etf_daily_prices/**/*.parquet",
        reference_series_data_path="s3://bucket/curated/reference_series",
    )

    assert "/curated/etf_daily_prices" in settings.market_data_path
    assert "/curated/reference_series" in settings.reference_series_data_path
    assert "/raw/" not in settings.market_data_path
    assert "/staging/" not in settings.market_data_path
    assert "/raw/" not in settings.reference_series_data_path
    assert "/staging/" not in settings.reference_series_data_path
