from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from market_simulator.data.duckdb_client import create_connection


REFERENCE_SERIES_COLUMNS = (
    "date",
    "symbol",
    "value",
    "unit",
    "source",
    "series_type",
    "open",
    "high",
    "low",
    "close",
)

@dataclass
class MarketDataBundle:
    tradable: pd.DataFrame
    references: dict[str, pd.DataFrame]

@dataclass
class MarketDataRepository:
    market_data_path: str
    reference_series_data_path: str | None = None
    supported_reference_series_symbols: tuple[str, ...] = ()
    duckdb_database: str = ":memory:"
    s3_region: str = "us-west-2"

    def _symbol_path(self, base_path: str, symbol: str) -> str:
        symbol = symbol.upper()
        base = base_path.rstrip("/")
        if "symbol=" in base and "*.parquet" in base:
            return base
        if "**/*.parquet" in base:
            return base.replace("**/*.parquet", f"symbol={symbol}/**/*.parquet")
        if "*.parquet" in base:
            return base
        return f"{base}/symbol={symbol}/**/*.parquet"

    def _etf_symbol_path(self, symbol: str) -> str:
        return self._symbol_path(self.market_data_path, symbol)

    def _reference_series_symbol_path(self, symbol: str) -> str:
        if not self.reference_series_data_path:
            raise ValueError("reference_series_data_path is required to load reference-series data")
        return self._symbol_path(self.reference_series_data_path, symbol)

    def _is_reference_series_symbol(self, symbol: str) -> bool:
        return symbol.upper() in {s.upper() for s in self.supported_reference_series_symbols}

    def _read_parquet_range(
        self,
        *,
        path: str,
        symbol: str,
        start_date: str,
        end_date: str,
        data_label: str,
    ) -> pd.DataFrame:
        query = f"""
            SELECT *
            FROM read_parquet('{path}')
            WHERE CAST(date AS DATE) BETWEEN ? AND ?
            ORDER BY date
        """
        conn = create_connection(self.duckdb_database, self.s3_region)
        try:
            df = conn.execute(query, [start_date, end_date]).df()
        except duckdb.Error as exc:
            raise ValueError(
                f"No {data_label} found for symbol={symbol.upper()} "
                f"in range {start_date}..{end_date} at {path}"
            ) from exc
        finally:
            conn.close()

        if df.empty:
            raise ValueError(
                f"No {data_label} found for symbol={symbol.upper()} "
                f"in range {start_date}..{end_date}"
            )

        return df

    def _normalize_dates_and_symbol(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = df.copy()
        if "date" not in df.columns:
            raise ValueError(f"Loaded data for symbol={symbol.upper()} is missing required date column")

        df["date"] = pd.to_datetime(df["date"])
        if "symbol" not in df.columns:
            df["symbol"] = symbol.upper()
        else:
            df["symbol"] = df["symbol"].fillna(symbol.upper()).astype(str).str.upper()

        return df.sort_values("date").reset_index(drop=True)

    def _normalize_etf_data(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = self._normalize_dates_and_symbol(df, symbol)
        expected_columns = [
            "date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "vwap",
            "transactions",
        ]
        missing_columns = [column for column in expected_columns if column not in df.columns]
        if missing_columns:
            raise ValueError(
                f"Loaded ETF bars for symbol={symbol.upper()} are missing columns: "
                f"{', '.join(missing_columns)}"
            )
        return df[expected_columns]

    def _normalize_reference_series_data(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = self._normalize_dates_and_symbol(df, symbol)
        if "value" not in df.columns and "close" in df.columns:
            df["value"] = df["close"]
        if "close" not in df.columns and "value" in df.columns:
            df["close"] = df["value"]

        ordered_columns = [column for column in REFERENCE_SERIES_COLUMNS if column in df.columns]
        remaining_columns = [column for column in df.columns if column not in ordered_columns]
        return df[ordered_columns + remaining_columns]

    def _read_etf_symbol(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._read_parquet_range(
            path=self._etf_symbol_path(symbol),
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            data_label="ETF bars",
        )
        return self._normalize_etf_data(df, symbol)

    def _read_reference_series_symbol(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        df = self._read_parquet_range(
            path=self._reference_series_symbol_path(symbol),
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            data_label="reference-series data",
        )
        return self._normalize_reference_series_data(df, symbol)

    def _read_symbol(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._read_etf_symbol(symbol, start_date, end_date)

    def _read_reference_symbol(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        if self._is_reference_series_symbol(symbol):
            return self._read_reference_series_symbol(symbol, start_date, end_date)
        return self._read_etf_symbol(symbol, start_date, end_date)

    def get_market_data(self, tradable_symbol: str, reference_symbols: list[str], start_date: str, end_date: str):
        tradable = self._read_symbol(tradable_symbol, start_date, end_date)
        refs = {s: self._read_reference_symbol(s, start_date, end_date) for s in reference_symbols}
        return MarketDataBundle(tradable=tradable, references=refs)
