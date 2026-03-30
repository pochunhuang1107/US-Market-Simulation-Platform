from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

class Settings(BaseModel):
    market_data_path: str = os.getenv(
        "MARKET_DATA_PATH",
        "s3://us-market-data-casper/curated/etf_daily_prices/**/*.parquet",
    )
    artifacts_dir: Path = Path(os.getenv("ARTIFACTS_DIR", "./data/local_artifacts"))
    duckdb_database: str = os.getenv("DUCKDB_DATABASE", ":memory:")
    s3_region: str = os.getenv("S3_REGION", "us-west-2")

def get_settings() -> Settings:
    return Settings()
