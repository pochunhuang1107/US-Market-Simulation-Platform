from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from market_simulator.data.duckdb_client import create_connection

@dataclass
class MarketDataBundle:
    tradable: pd.DataFrame
    references: dict[str, pd.DataFrame]

@dataclass
class MarketDataRepository:
    market_data_path: str
    duckdb_database: str = ":memory:"
    s3_region: str = "us-west-2"

    def _symbol_path(self, symbol: str) -> str:
        base = self.market_data_path.rstrip("/")
        if "**/*.parquet" in base:
            return base.replace("**/*.parquet", f"symbol={symbol}/**/*.parquet")
        return f"{base}/symbol={symbol}/**/*.parquet"

    def _read_symbol(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        path = self._symbol_path(symbol)
        query = f'''
            SELECT
                CAST(date AS DATE) AS date,
                symbol,
                CAST(open AS DOUBLE) AS open,
                CAST(high AS DOUBLE) AS high,
                CAST(low AS DOUBLE) AS low,
                CAST(close AS DOUBLE) AS close,
                CAST(volume AS DOUBLE) AS volume,
                CAST(vwap AS DOUBLE) AS vwap,
                CAST(transactions AS DOUBLE) AS transactions
            FROM read_parquet('{path}')
            WHERE CAST(date AS DATE) BETWEEN ? AND ?
            ORDER BY date
        '''
        conn = create_connection(self.duckdb_database, self.s3_region)
        try:
            df = conn.execute(query, [start_date, end_date]).df()
        finally:
            conn.close()

        if df.empty:
            raise ValueError(f"No bars found for symbol={symbol} in range {start_date}..{end_date}")

        df["date"] = pd.to_datetime(df["date"])
        return df.reset_index(drop=True)

    def get_market_data(self, tradable_symbol: str, reference_symbols: list[str], start_date: str, end_date: str):
        tradable = self._read_symbol(tradable_symbol, start_date, end_date)
        refs = {s: self._read_symbol(s, start_date, end_date) for s in reference_symbols}
        return MarketDataBundle(tradable=tradable, references=refs)
