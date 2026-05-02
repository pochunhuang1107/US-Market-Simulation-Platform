from __future__ import annotations

import pandas as pd
import pytest

from market_simulator.data.repository import MarketDataRepository


def _write_parquet(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _etf_rows(symbol: str, closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2021-01-04", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": closes,
            "high": [close + 1.0 for close in closes],
            "low": [close - 1.0 for close in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
            "vwap": closes,
            "transactions": [10_000.0] * len(closes),
        }
    )


def _repository(tmp_path) -> MarketDataRepository:
    return MarketDataRepository(
        market_data_path=str(tmp_path / "curated" / "etf_daily_prices"),
        reference_series_data_path=str(tmp_path / "curated" / "reference_series"),
        supported_reference_series_symbols=("VIX", "DGS10"),
    )


def test_get_market_data_routes_etf_and_reference_series_symbols(tmp_path) -> None:
    _write_parquet(
        _etf_rows("QQQ", [100.0, 101.0, 102.0]),
        tmp_path / "curated" / "etf_daily_prices" / "symbol=QQQ" / "year=2021" / "data.parquet",
    )
    _write_parquet(
        _etf_rows("SPY", [370.0, 371.0, 372.0]),
        tmp_path / "curated" / "etf_daily_prices" / "symbol=SPY" / "year=2021" / "data.parquet",
    )
    _write_parquet(
        pd.DataFrame(
            {
                "date": pd.date_range("2021-01-04", periods=3, freq="B"),
                "value": [22.0, 21.0, 20.0],
                "unit": ["index"] * 3,
                "source": ["CBOE"] * 3,
                "series_type": ["volatility_index"] * 3,
                "open": [22.5, 21.5, 20.5],
                "high": [23.0, 22.0, 21.0],
                "low": [21.5, 20.5, 19.5],
                "close": [22.25, 21.25, 20.25],
            }
        ),
        tmp_path / "curated" / "reference_series" / "symbol=VIX" / "year=2021" / "data.parquet",
    )
    _write_parquet(
        pd.DataFrame(
            {
                "date": pd.date_range("2021-01-04", periods=3, freq="B"),
                "value": [0.93, 0.95, 0.96],
                "unit": ["percent"] * 3,
                "source": ["FRED"] * 3,
                "series_type": ["interest_rate"] * 3,
            }
        ),
        tmp_path / "curated" / "reference_series" / "symbol=DGS10" / "year=2021" / "data.parquet",
    )

    bundle = _repository(tmp_path).get_market_data(
        tradable_symbol="QQQ",
        reference_symbols=["SPY", "VIX", "DGS10"],
        start_date="2021-01-05",
        end_date="2021-01-06",
    )

    assert bundle.tradable["symbol"].tolist() == ["QQQ", "QQQ"]
    assert bundle.tradable["close"].tolist() == [101.0, 102.0]

    spy = bundle.references["SPY"]
    assert "value" not in spy.columns
    assert spy["symbol"].tolist() == ["SPY", "SPY"]
    assert spy["close"].tolist() == [371.0, 372.0]

    vix = bundle.references["VIX"]
    assert vix["date"].tolist() == list(pd.to_datetime(["2021-01-05", "2021-01-06"]))
    assert vix["symbol"].tolist() == ["VIX", "VIX"]
    assert vix["value"].tolist() == [21.0, 20.0]
    assert vix["close"].tolist() == [21.25, 20.25]
    assert vix["unit"].tolist() == ["index", "index"]
    assert vix["source"].tolist() == ["CBOE", "CBOE"]
    assert vix["series_type"].tolist() == ["volatility_index", "volatility_index"]

    dgs10 = bundle.references["DGS10"]
    assert dgs10["symbol"].tolist() == ["DGS10", "DGS10"]
    assert dgs10["value"].tolist() == [0.95, 0.96]
    assert dgs10["close"].tolist() == [0.95, 0.96]
    assert dgs10["date"].is_monotonic_increasing


def test_reference_series_missing_data_raises_clear_error(tmp_path) -> None:
    _write_parquet(
        _etf_rows("QQQ", [100.0]),
        tmp_path / "curated" / "etf_daily_prices" / "symbol=QQQ" / "year=2021" / "data.parquet",
    )

    with pytest.raises(ValueError, match="No reference-series data found for symbol=VIX"):
        _repository(tmp_path).get_market_data(
            tradable_symbol="QQQ",
            reference_symbols=["VIX"],
            start_date="2021-01-04",
            end_date="2021-01-05",
        )
