from __future__ import annotations

from dataclasses import dataclass
from glob import glob
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from market_simulator.data.duckdb_client import create_connection
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

SUPPORTED_MODEL_SIGNAL_FILE_EXTENSIONS = (".csv", ".json", ".jsonl", ".parquet")

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


def _normalize_model_version(model_version: str) -> str:
    normalized_version = model_version.strip()
    if not normalized_version:
        raise ValueError("model_version must be present and non-empty")
    if "/" in normalized_version or "\\" in normalized_version:
        raise ValueError("model_version must not contain path separators")
    return normalized_version


def _is_uri(path: str | Path) -> bool:
    return "://" in str(path)


def _has_glob_pattern(path: str | Path) -> bool:
    return any(char in str(path) for char in "*?[")


def _model_signal_suffix(path: str | Path) -> str:
    return Path(str(path).split("?", 1)[0]).suffix.lower()


def _duckdb_literal(value: str) -> str:
    return value.replace("'", "''")


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


def _read_model_signal_file(path: str | Path) -> pd.DataFrame:
    suffix = _model_signal_suffix(path)

    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    if suffix == ".parquet":
        return pd.read_parquet(path)

    raise ValueError(
        "Unsupported model signal file extension. "
        "Use .csv, .json, .jsonl, or .parquet."
    )


def _read_model_signal_uri(
    path: str,
    *,
    duckdb_database: str = ":memory:",
    s3_region: str = "us-west-2",
) -> pd.DataFrame:
    suffix = _model_signal_suffix(path)
    if suffix == ".parquet":
        read_expression = f"read_parquet('{_duckdb_literal(path)}')"
    elif suffix == ".csv":
        read_expression = f"read_csv_auto('{_duckdb_literal(path)}')"
    else:
        raise ValueError(
            "Unsupported model signal URI extension. Use .csv or .parquet."
        )

    conn = create_connection(duckdb_database, s3_region)
    try:
        return conn.execute(f"SELECT * FROM {read_expression}").df()
    except duckdb.Error as exc:
        raise ValueError(f"Unable to load model signal artifact at {path}") from exc
    finally:
        conn.close()


def load_model_signal_frame(
    path: str | Path,
    *,
    supported_symbols: Iterable[str] | None = None,
    reject_label_columns: bool = True,
    duckdb_database: str = ":memory:",
    s3_region: str = "us-west-2",
) -> pd.DataFrame:
    """Load one CSV, JSON/JSONL, or parquet model-signal artifact and validate it."""

    if _is_uri(path):
        frame = _read_model_signal_uri(
            str(path),
            duckdb_database=duckdb_database,
            s3_region=s3_region,
        )
    else:
        artifact_path = Path(path)
        if not artifact_path.exists():
            raise ValueError(f"Model signal path does not exist: {artifact_path}")
        if not artifact_path.is_file():
            raise ValueError(f"Model signal path is not a file: {artifact_path}")
        frame = _read_model_signal_file(artifact_path)

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
    """Repository for precomputed point-in-time model-signal artifacts."""

    base_path: str | Path
    file_name: str = "signals.parquet"
    supported_symbols: Iterable[str] | None = None
    duckdb_database: str = ":memory:"
    s3_region: str = "us-west-2"

    def path_for_model_version(self, model_version: str) -> str | Path:
        normalized_version = _normalize_model_version(model_version)
        if _is_uri(self.base_path):
            base = str(self.base_path)
            if "<VERSION>" in base:
                return base.replace("<VERSION>", normalized_version)
            return f"{base.rstrip('/')}/model_version={normalized_version}/{self.file_name}"
        return (
            Path(self.base_path)
            / f"model_version={normalized_version}"
            / self.file_name
        )

    def _local_paths(self, model_version: str | None) -> list[Path]:
        base = Path(self.base_path)
        if _has_glob_pattern(base):
            matches = [
                Path(path)
                for path in glob(str(base), recursive=True)
                if Path(path).is_file()
                and Path(path).suffix.lower() in SUPPORTED_MODEL_SIGNAL_FILE_EXTENSIONS
            ]
            if not matches:
                raise ValueError(f"No model signal files matched path: {base}")
            return sorted(matches)

        if base.is_file():
            if base.suffix.lower() not in SUPPORTED_MODEL_SIGNAL_FILE_EXTENSIONS:
                raise ValueError(
                    "Unsupported model signal file extension. "
                    "Use .csv, .json, .jsonl, or .parquet."
                )
            return [base]

        if base.is_dir():
            if model_version is not None:
                version_path = Path(self.path_for_model_version(model_version))
                if version_path.exists():
                    return [version_path]
                version_dir = base / f"model_version={_normalize_model_version(model_version)}"
                if version_dir.is_dir():
                    matches = [
                        path
                        for path in version_dir.rglob("*")
                        if path.is_file()
                        and path.suffix.lower() in SUPPORTED_MODEL_SIGNAL_FILE_EXTENSIONS
                    ]
                    if matches:
                        return sorted(matches)

            matches = [
                path
                for path in base.rglob("*")
                if path.is_file()
                and path.suffix.lower() in SUPPORTED_MODEL_SIGNAL_FILE_EXTENSIONS
            ]
            if not matches:
                raise ValueError(f"No model signal files found under directory: {base}")
            return sorted(matches)

        raise ValueError(f"Model signal path does not exist: {base}")

    def _uri_path(self, model_version: str | None) -> str:
        base = str(self.base_path)
        if "<VERSION>" in base:
            if model_version is None:
                raise ValueError(
                    "model_version is required when MODEL_SIGNAL_DATA_PATH contains <VERSION>"
                )
            return base.replace("<VERSION>", _normalize_model_version(model_version))
        if _has_glob_pattern(base) or _model_signal_suffix(base):
            return base
        if model_version is not None:
            return str(self.path_for_model_version(model_version))
        return base

    def _load_raw_frame(self, model_version: str | None) -> pd.DataFrame:
        if _is_uri(self.base_path):
            return _read_model_signal_uri(
                self._uri_path(model_version),
                duckdb_database=self.duckdb_database,
                s3_region=self.s3_region,
            )

        frames = [
            _read_model_signal_file(path)
            for path in self._local_paths(model_version)
        ]
        if not frames:
            raise ValueError(f"No model signal files found at {self.base_path}")
        return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    def load(
        self,
        *,
        model_version: str | None = None,
        universe: Iterable[str] | None = None,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
        reject_label_columns: bool = True,
    ) -> pd.DataFrame:
        """Load, validate, and filter model-signal rows for deterministic execution."""

        raw = self._load_raw_frame(model_version)
        validated = validate_model_signal_frame(
            raw,
            supported_symbols=self.supported_symbols,
            reject_label_columns=reject_label_columns,
        )

        filtered = validated
        if model_version is not None:
            normalized_version = _normalize_model_version(model_version)
            filtered = filtered[filtered["model_version"] == normalized_version]

        if universe is not None:
            symbols = _normalized_supported_symbols(universe)
            filtered = filtered[filtered["symbol"].isin(symbols)]

        if start_date is not None:
            start = pd.Timestamp(start_date).normalize()
            filtered = filtered[filtered["date"] >= start]

        if end_date is not None:
            end = pd.Timestamp(end_date).normalize()
            filtered = filtered[filtered["date"] <= end]

        return filtered.sort_values(list(MODEL_SIGNAL_IDENTITY_COLUMNS)).reset_index(
            drop=True
        )

    def load_dataset(
        self,
        *,
        model_version: str | None = None,
        universe: Iterable[str] | None = None,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
    ) -> ModelSignalDataset:
        return ModelSignalDataset(
            self.load(
                model_version=model_version,
                universe=universe,
                start_date=start_date,
                end_date=end_date,
            )
        )

    def load_model_version(self, model_version: str) -> ModelSignalDataset:
        return self.load_dataset(model_version=model_version)
