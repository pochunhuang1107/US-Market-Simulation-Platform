from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from urllib.parse import urlparse

import boto3
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from market_simulator.settings import get_settings


@dataclass(frozen=True)
class EtfHistoryRange:
    symbol: str
    first_available_date: date
    last_available_date: date


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ValueError(f"Invalid S3 URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


@lru_cache(maxsize=1)
def _load_metadata_map(metadata_s3_uri: str) -> dict[str, EtfHistoryRange]:
    bucket, key = _parse_s3_uri(metadata_s3_uri)
    s3 = boto3.client("s3")

    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return {}
        raise

    table = pq.read_table(io.BytesIO(response["Body"].read()))
    rows = table.to_pylist()

    result: dict[str, EtfHistoryRange] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        result[symbol] = EtfHistoryRange(
            symbol=symbol,
            first_available_date=date.fromisoformat(str(row["first_available_date"])),
            last_available_date=date.fromisoformat(str(row["last_available_date"])),
        )
    return result


def get_etf_history_range(symbol: str) -> EtfHistoryRange | None:
    settings = get_settings()
    metadata = _load_metadata_map(settings.etf_metadata_s3_uri)
    return metadata.get(symbol.upper())