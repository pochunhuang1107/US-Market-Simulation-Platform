#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_simulator.data.model_signals import (  # noqa: E402
    MODEL_SIGNAL_IDENTITY_COLUMNS,
    REQUIRED_MODEL_SIGNAL_COLUMNS,
    ModelSignalRepository,
)


def _format_date(value: pd.Timestamp | None) -> str:
    if value is None or pd.isna(value):
        return "none"
    return str(pd.Timestamp(value).date())


def _format_values(values: Iterable[object]) -> str:
    formatted = [str(value) for value in values]
    return ", ".join(formatted) if formatted else "none"


def _missing_required_columns(frame: pd.DataFrame | None) -> list[str]:
    if frame is None:
        return []
    return [column for column in REQUIRED_MODEL_SIGNAL_COLUMNS if column not in frame.columns]


def _duplicate_count(frame: pd.DataFrame | None) -> int | str:
    if frame is None:
        return "unknown"
    if any(column not in frame.columns for column in MODEL_SIGNAL_IDENTITY_COLUMNS):
        return "unknown"

    identity = frame.loc[:, list(MODEL_SIGNAL_IDENTITY_COLUMNS)].copy()
    identity["date"] = pd.to_datetime(
        identity["date"],
        errors="coerce",
        format="mixed",
    ).dt.normalize()
    identity["symbol"] = identity["symbol"].astype("string").str.strip().str.upper()
    identity["model_version"] = identity["model_version"].astype("string").str.strip()
    return int(identity.duplicated(list(MODEL_SIGNAL_IDENTITY_COLUMNS), keep=False).sum())


def _load_raw_for_diagnostics(repository: ModelSignalRepository) -> pd.DataFrame | None:
    try:
        return repository._load_raw_frame(model_version=None)
    except Exception:
        return None


def _print_summary(
    frame: pd.DataFrame | None,
    *,
    raw_frame: pd.DataFrame | None,
    valid: bool,
    error: str | None = None,
) -> None:
    print(f"status: {'valid' if valid else 'invalid'}")

    if frame is not None:
        print(f"rows: {len(frame)}")
        print(f"date_min: {_format_date(frame['date'].min() if len(frame) else None)}")
        print(f"date_max: {_format_date(frame['date'].max() if len(frame) else None)}")
        symbols = tuple(sorted(frame["symbol"].dropna().astype(str).unique()))
        model_versions = tuple(sorted(frame["model_version"].dropna().astype(str).unique()))
        print(f"symbol_count: {len(symbols)}")
        print(f"symbols: {_format_values(symbols)}")
        print(f"model_versions: {_format_values(model_versions)}")
    else:
        print("rows: unknown")
        print("date_min: unknown")
        print("date_max: unknown")
        print("symbol_count: unknown")
        print("symbols: unknown")
        print("model_versions: unknown")

    missing = _missing_required_columns(raw_frame if raw_frame is not None else frame)
    print(f"missing_required_columns: {_format_values(missing)}")
    print(f"duplicate_count: {_duplicate_count(raw_frame if raw_frame is not None else frame)}")

    if error:
        print(f"error: {error}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a model signal export artifact for platform ingestion.",
    )
    parser.add_argument("--path", required=True, help="CSV, JSON/JSONL, parquet, glob, or directory path.")
    parser.add_argument("--model-version", help="Optional model_version filter.")
    parser.add_argument("--start-date", help="Optional inclusive start-date filter.")
    parser.add_argument("--end-date", help="Optional inclusive end-date filter.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = ModelSignalRepository(args.path)
    raw_frame = _load_raw_for_diagnostics(repository)

    try:
        frame = repository.load(
            model_version=args.model_version,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        _print_summary(None, raw_frame=raw_frame, valid=False, error=str(exc))
        return 1

    _print_summary(frame, raw_frame=raw_frame, valid=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
