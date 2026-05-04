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

DEFAULT_SUPPORTED_REFERENCE_SERIES_SYMBOLS = ",".join(
    [
        "VIX",
        "VIX9D",
        "VXEEM",
        "DGS10",
        "DGS2",
        "T10Y2Y",
        "DFF",
    ]
)


class Settings(BaseModel):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/market_simulator",
    )

    market_data_path: str = os.getenv(
        "MARKET_DATA_PATH",
        "s3://your-market-data-bucket/curated/etf_daily_prices/**/*.parquet",
    )
    etf_metadata_s3_uri: str = os.getenv(
        "ETF_METADATA_S3_URI",
        "s3://your-market-data-bucket/curated/reference/etf_symbol_metadata/data.parquet",
    )
    reference_series_data_path: str = os.getenv(
        "REFERENCE_SERIES_DATA_PATH",
        "s3://your-market-data-bucket/curated/reference_series",
    )
    reference_series_metadata_s3_uri: str = os.getenv(
        "REFERENCE_SERIES_METADATA_S3_URI",
        "s3://your-market-data-bucket/curated/reference/reference_series_metadata/data.parquet",
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
    auth_mode: str | None = os.getenv("AUTH_MODE")

    dev_default_user_id: str | None = os.getenv(
        "DEV_DEFAULT_USER_ID",
        "00000000-0000-0000-0000-000000000001",
    )

    enable_dev_admin_override: bool = os.getenv(
        "ENABLE_DEV_ADMIN_OVERRIDE",
        "false",
    ).lower() == "true"

    dev_admin_user_ids_csv: str = os.getenv("DEV_ADMIN_USER_IDS", "")

    dev_admin_monthly_price_usd: float = float(
        os.getenv("DEV_ADMIN_MONTHLY_PRICE_USD", "0")
    )
    dev_admin_daily_free_runs: int = int(
        os.getenv("DEV_ADMIN_DAILY_FREE_RUNS", "999999")
    )
    dev_admin_max_saved_strategies: int = int(
        os.getenv("DEV_ADMIN_MAX_SAVED_STRATEGIES", "999999")
    )
    dev_admin_max_tracked_strategies: int = int(
        os.getenv("DEV_ADMIN_MAX_TRACKED_STRATEGIES", "999999")
    )
    dev_admin_builder_prompt_daily_limit: int = int(
        os.getenv("DEV_ADMIN_BUILDER_PROMPT_DAILY_LIMIT", "999999")
    )
    dev_admin_builder_prompt_max_chars: int = int(
        os.getenv("DEV_ADMIN_BUILDER_PROMPT_MAX_CHARS", "20000")
    )
    dev_admin_max_backtest_years: int = int(
        os.getenv("DEV_ADMIN_MAX_BACKTEST_YEARS", "25")
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
    supported_reference_series_symbols_csv: str = os.getenv(
        "SUPPORTED_REFERENCE_SERIES_SYMBOLS",
        DEFAULT_SUPPORTED_REFERENCE_SERIES_SYMBOLS,
    )

    @property
    def dev_admin_user_ids(self) -> tuple[str, ...]:
        values = {
            user_id.strip()
            for user_id in self.dev_admin_user_ids_csv.split(",")
            if user_id.strip()
        }

        if not values and self.dev_default_user_id:
            values.add(self.dev_default_user_id)

        return tuple(sorted(values))

    @property
    def supported_etf_symbols(self) -> tuple[str, ...]:
        values = {
            symbol.strip().upper()
            for symbol in self.supported_etf_symbols_csv.split(",")
            if symbol.strip()
        }
        return tuple(sorted(values))

    @property
    def supported_reference_series_symbols(self) -> tuple[str, ...]:
        values = {
            symbol.strip().upper()
            for symbol in self.supported_reference_series_symbols_csv.split(",")
            if symbol.strip()
        }
        return tuple(sorted(values))

    @property
    def supported_data_start(self) -> date:
        return date.fromisoformat(self.supported_data_start_date)

    @property
    def supported_data_end(self) -> date:
        return date.fromisoformat(self.supported_data_end_date)

    @property
    def normalized_env(self) -> str:
        return self.env.strip().lower()

    @property
    def is_protected_env(self) -> bool:
        return self.normalized_env in {"prod", "production", "beta"}

    @property
    def resolved_auth_mode(self) -> str:
        if self.is_protected_env:
            return "required"

        if self.auth_mode:
            return self.auth_mode.strip().lower()

        if self.normalized_env in {"local", "dev", "development", "test", "testing"}:
            return "dev"

        return "required"

    @property
    def is_dev_auth_enabled(self) -> bool:
        return self.resolved_auth_mode in {"dev", "local", "test"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
