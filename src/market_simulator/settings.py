from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


DEFAULT_SUPPORTED_ETF_SYMBOLS = ",".join(
    [
        "SPY",
        "QQQ",
        "DIA",
        "IWM",
        "VTI",
        "GLD",
        "SLV",
        "TLT",
        "IEF",
        "HYG",
        "LQD",
        "XLF",
        "XLK",
        "XLE",
        "XLV",
        "XLY",
        "XLP",
        "XLI",
        "XLU",
        "XLB",
        "XLRE",
        "ARKK",
        "VUG",
        "VTV",
        "QUAL",
        "MTUM",
        "IBIT",
    ]
)


class Settings(BaseModel):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/market_simulator",
    )

    market_data_path: str = os.getenv(
        "MARKET_DATA_PATH",
        "s3://us-market-data-casper/curated/etf_daily_prices/**/*.parquet",
    )
    duckdb_database: str = os.getenv("DUCKDB_DATABASE", ":memory:")
    s3_region: str = os.getenv("S3_REGION", "us-west-2")

    artifacts_dir: Path = Path(
        os.getenv("ARTIFACTS_DIR", "./data/local_artifacts")
    )
    artifact_storage_backend: str = os.getenv("ARTIFACT_STORAGE_BACKEND", "LOCAL")
    artifact_s3_bucket: str | None = os.getenv("ARTIFACT_S3_BUCKET")
    artifact_s3_prefix: str = os.getenv("ARTIFACT_S3_PREFIX", "artifacts")
    artifact_s3_region: str = os.getenv(
        "ARTIFACT_S3_REGION",
        os.getenv("S3_REGION", "us-west-2"),
    )
    artifact_presign_ttl_seconds: int = int(
        os.getenv("ARTIFACT_PRESIGN_TTL_SECONDS", "3600")
    )

    env: str = os.getenv("ENV", "local")

    dev_default_user_id: str | None = os.getenv(
        "DEV_DEFAULT_USER_ID",
        "00000000-0000-0000-0000-000000000001",
    )

    supported_data_start_date: str = os.getenv(
        "SUPPORTED_DATA_START_DATE",
        "2018-01-02",
    )
    supported_data_end_date: str = os.getenv(
        "SUPPORTED_DATA_END_DATE",
        date.today().isoformat(),
    )
    supported_etf_symbols_csv: str = os.getenv(
        "SUPPORTED_ETF_SYMBOLS",
        DEFAULT_SUPPORTED_ETF_SYMBOLS,
    )

    @property
    def supported_etf_symbols(self) -> tuple[str, ...]:
        values = {
            symbol.strip().upper()
            for symbol in self.supported_etf_symbols_csv.split(",")
            if symbol.strip()
        }
        return tuple(sorted(values))

    @property
    def supported_data_start(self) -> date:
        return date.fromisoformat(self.supported_data_start_date)

    @property
    def supported_data_end(self) -> date:
        return date.fromisoformat(self.supported_data_end_date)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings