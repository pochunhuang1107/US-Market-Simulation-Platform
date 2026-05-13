from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from market_simulator.settings import get_settings


REQUIRED_MODEL_SIGNAL_COLUMNS = (
    "date",
    "symbol",
    "model_version",
    "score",
)

OPTIONAL_MODEL_SIGNAL_COLUMNS = (
    "predicted_return",
    "rank",
    "confidence",
    "signal_bucket",
    "feature_set_version",
    "label_horizon_days",
    "created_at",
)

MODEL_SIGNAL_IDENTITY_COLUMNS = ("date", "symbol", "model_version")

DEFAULT_MODEL_SIGNAL_PATH_TEMPLATE = (
    "curated/model_signals/model_version=<VERSION>/signals.parquet"
)

FORBIDDEN_RUNTIME_LABEL_COLUMNS = frozenset(
    {
        "actual_return",
        "future_return",
        "forward_return",
        "label",
        "outcome",
        "realized_return",
        "target",
        "target_return",
        "next_return",
    }
)

FORBIDDEN_RUNTIME_LABEL_PREFIXES = (
    "actual_return_",
    "future_return_",
    "forward_return_",
    "label_return_",
    "next_return_",
    "realized_return_",
    "target_return_",
)


def _default_supported_symbols() -> tuple[str, ...]:
    return get_settings().supported_etf_symbols


def _normalized_supported_symbols(
    supported_symbols: Iterable[str] | None,
) -> set[str]:
    symbols = (
        supported_symbols
        if supported_symbols is not None
        else _default_supported_symbols()
    )
    return {symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()}


def _is_forbidden_runtime_label_column(column: str) -> bool:
    normalized = column.strip().lower()
    if normalized in {name.lower() for name in REQUIRED_MODEL_SIGNAL_COLUMNS}:
        return False
    if normalized in {name.lower() for name in OPTIONAL_MODEL_SIGNAL_COLUMNS}:
        return False
    return normalized in FORBIDDEN_RUNTIME_LABEL_COLUMNS or normalized.startswith(
        FORBIDDEN_RUNTIME_LABEL_PREFIXES
    )


def _reject_runtime_label_columns(columns: Iterable[str]) -> None:
    forbidden = sorted(
        column for column in columns if _is_forbidden_runtime_label_column(column)
    )
    if forbidden:
        raise ValueError(
            "Model signal files must not include runtime lookahead label columns: "
            f"{', '.join(forbidden)}. Export research labels in a separate file."
        )


def _coerce_numeric_column(
    df: pd.DataFrame,
    column: str,
    *,
    required: bool,
) -> pd.Series:
    original = df[column]
    coerced = pd.to_numeric(original, errors="coerce")
    present = original.notna() & original.astype(str).str.strip().ne("")
    invalid = coerced.isna() if required else coerced.isna() & present
    if invalid.any():
        bad_rows = [str(index) for index in df.index[invalid].tolist()[:5]]
        raise ValueError(
            f"{column} must be numeric; invalid rows: {', '.join(bad_rows)}"
        )
    return coerced


def validate_model_signal_frame(
    frame: pd.DataFrame,
    *,
    supported_symbols: Iterable[str] | None = None,
    reject_label_columns: bool = True,
) -> pd.DataFrame:
    """Validate and normalize a precomputed model-signal dataframe.

    The returned frame is a copy. It is suitable for future deterministic
    Strategy V2 ingestion, but this module does not execute strategy logic.
    """

    missing_columns = [
        column for column in REQUIRED_MODEL_SIGNAL_COLUMNS if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            "Model signal file is missing required columns: "
            f"{', '.join(missing_columns)}"
        )

    if reject_label_columns:
        _reject_runtime_label_columns(frame.columns)

    valid_symbols = _normalized_supported_symbols(supported_symbols)
    df = frame.copy()

    parsed_dates = pd.to_datetime(df["date"], errors="coerce", format="mixed")
    if parsed_dates.isna().any():
        bad_rows = [str(index) for index in df.index[parsed_dates.isna()].tolist()[:5]]
        raise ValueError(
            "date values must parse correctly; "
            f"invalid rows: {', '.join(bad_rows)}"
        )
    df["date"] = parsed_dates.dt.normalize()

    symbols = df["symbol"].astype("string").str.strip().str.upper()
    missing_symbols = symbols.isna() | symbols.eq("")
    if missing_symbols.any():
        bad_rows = [str(index) for index in df.index[missing_symbols].tolist()[:5]]
        raise ValueError(f"symbol must be present; invalid rows: {', '.join(bad_rows)}")

    unsupported_symbols = sorted(set(symbols.dropna()) - valid_symbols)
    if unsupported_symbols:
        raise ValueError(
            "Model signal file contains unsupported ETF symbols: "
            f"{', '.join(unsupported_symbols)}"
        )
    df["symbol"] = symbols.astype(str)

    model_versions = df["model_version"].astype("string").str.strip()
    missing_model_versions = model_versions.isna() | model_versions.eq("")
    if missing_model_versions.any():
        bad_rows = [str(index) for index in df.index[missing_model_versions].tolist()[:5]]
        raise ValueError(
            "model_version must be present and non-empty; "
            f"invalid rows: {', '.join(bad_rows)}"
        )
    df["model_version"] = model_versions.astype(str)

    df["score"] = _coerce_numeric_column(df, "score", required=True)

    if "rank" in df.columns:
        df["rank"] = _coerce_numeric_column(df, "rank", required=False)

    if "confidence" in df.columns:
        df["confidence"] = _coerce_numeric_column(df, "confidence", required=False)
        confidence_values = df["confidence"].dropna()
        invalid_confidence = ~confidence_values.between(0, 1, inclusive="both")
        if invalid_confidence.any():
            bad_rows = [
                str(index)
                for index in confidence_values.index[invalid_confidence].tolist()[:5]
            ]
            raise ValueError(
                "confidence must be between 0 and 1 inclusive; "
                f"invalid rows: {', '.join(bad_rows)}"
            )

    duplicate_rows = df.duplicated(list(MODEL_SIGNAL_IDENTITY_COLUMNS), keep=False)
    if duplicate_rows.any():
        examples = df.loc[duplicate_rows, list(MODEL_SIGNAL_IDENTITY_COLUMNS)].head(5)
        example_keys = [
            f"{row.date.date()}/{row.symbol}/{row.model_version}"
            for row in examples.itertuples(index=False)
        ]
        raise ValueError(
            "Model signal file contains duplicate date/symbol/model_version rows: "
            f"{', '.join(example_keys)}"
        )

    return df


def load_model_signal_frame(
    path: str | Path,
    *,
    supported_symbols: Iterable[str] | None = None,
    reject_label_columns: bool = True,
) -> pd.DataFrame:
    """Load a local CSV, JSON/JSONL, or parquet model-signal artifact and validate it."""

    artifact_path = Path(path)
    suffix = artifact_path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(artifact_path)
    elif suffix in {".json", ".jsonl"}:
        frame = pd.read_json(artifact_path, lines=suffix == ".jsonl")
    elif suffix == ".parquet":
        frame = pd.read_parquet(artifact_path)
    else:
        raise ValueError(
            "Unsupported model signal file extension. "
            "Use .csv, .json, .jsonl, or .parquet."
        )

    return validate_model_signal_frame(
        frame,
        supported_symbols=supported_symbols,
        reject_label_columns=reject_label_columns,
    )


@dataclass(frozen=True)
class ModelSignalDataset:
    """Validated model signal records ready for future Strategy V2 integration."""

    frame: pd.DataFrame

    @classmethod
    def from_frame(
        cls,
        frame: pd.DataFrame,
        *,
        supported_symbols: Iterable[str] | None = None,
        reject_label_columns: bool = True,
    ) -> "ModelSignalDataset":
        return cls(
            validate_model_signal_frame(
                frame,
                supported_symbols=supported_symbols,
                reject_label_columns=reject_label_columns,
            )
        )

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.frame["symbol"].unique()))

    @property
    def model_versions(self) -> tuple[str, ...]:
        return tuple(sorted(self.frame["model_version"].unique()))

    @property
    def date_range(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.frame["date"].min(), self.frame["date"].max()


@dataclass(frozen=True)
class ModelSignalRepository:
    """Local artifact repository placeholder for future Strategy V2 signal loading."""

    base_path: str | Path
    file_name: str = "signals.parquet"
    supported_symbols: Iterable[str] | None = None

    def path_for_model_version(self, model_version: str) -> Path:
        normalized_version = model_version.strip()
        if not normalized_version:
            raise ValueError("model_version must be present and non-empty")
        if "/" in normalized_version or "\\" in normalized_version:
            raise ValueError("model_version must not contain path separators")
        return (
            Path(self.base_path)
            / f"model_version={normalized_version}"
            / self.file_name
        )

    def load_model_version(self, model_version: str) -> ModelSignalDataset:
        return ModelSignalDataset(
            load_model_signal_frame(
                self.path_for_model_version(model_version),
                supported_symbols=self.supported_symbols,
            )
        )
