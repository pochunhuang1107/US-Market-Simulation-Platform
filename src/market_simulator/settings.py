from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    # ------------------------
    # Database
    # ------------------------
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/market_simulator",
    )

    # ------------------------
    # Data layer
    # ------------------------
    market_data_path: str = os.getenv(
        "MARKET_DATA_PATH",
        "s3://us-market-data-casper/curated/etf_daily_prices/**/*.parquet",
    )

    duckdb_database: str = os.getenv("DUCKDB_DATABASE", ":memory:")
    s3_region: str = os.getenv("S3_REGION", "us-west-2")

    # ------------------------
    # Artifacts
    # ------------------------
    artifacts_dir: Path = Path(
        os.getenv("ARTIFACTS_DIR", "./data/local_artifacts")
    )

    # ------------------------
    # Runtime flags (optional)
    # ------------------------
    env: str = os.getenv("ENV", "local")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings