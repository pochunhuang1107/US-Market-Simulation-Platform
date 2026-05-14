from __future__ import annotations

import json
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
DEFAULT_MODEL_SIGNAL_MANIFEST_FILE_NAME = "model_signal_manifest.json"

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


def _is_supported_model_signal_file(path: str | Path) -> bool:
    candidate = Path(path)
    return (
        candidate.name != DEFAULT_MODEL_SIGNAL_MANIFEST_FILE_NAME
        and candidate.suffix.lower() in SUPPORTED_MODEL_SIGNAL_FILE_EXTENSIONS
    )


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


@dataclass(frozen=True)
class ModelSignalManifest:
    model_version: str
    feature_set_version: str | None = None
    label_horizon_days: int | None = None
    latest_signal_date: pd.Timestamp | None = None
    row_count: int | None = None
    symbol_count: int | None = None
    export_created_at: str | None = None
    candidate_id: str | None = None
    artifact_path: str | None = None
    status: str | None = None
    warnings: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "feature_set_version": self.feature_set_version,
            "label_horizon_days": self.label_horizon_days,
            "latest_signal_date": (
                self.latest_signal_date.date().isoformat()
                if self.latest_signal_date is not None
                else None
            ),
            "row_count": self.row_count,
            "symbol_count": self.symbol_count,
            "export_created_at": self.export_created_at,
            "candidate_id": self.candidate_id,
            "status": self.status,
            "warnings": list(self.warnings),
        }


def _optional_int(value: object, *, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"manifest {field_name} must be an integer") from exc


def _manifest_warnings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Iterable):
        return tuple(str(warning) for warning in value if str(warning).strip())
    return (str(value),)


def validate_model_signal_manifest(
    manifest: dict[str, object],
    *,
    model_version: str,
    require_ready: bool = True,
) -> ModelSignalManifest:
    """Validate a model-signal export manifest without exposing storage paths."""

    requested_model_version = _normalize_model_version(model_version)
    manifest_model_version = str(manifest.get("model_version", "")).strip()
    if not manifest_model_version:
        raise ValueError("manifest model_version must be present and non-empty")
    if manifest_model_version != requested_model_version:
        raise ValueError(
            "manifest model_version does not match requested model_version"
        )

    status_value = manifest.get("status")
    status = str(status_value).strip().lower() if status_value is not None else None
    if require_ready and status != "ready":
        raise ValueError("manifest status must be ready for normal use")

    latest_signal_date_value = manifest.get("latest_signal_date")
    latest_signal_date = None
    if latest_signal_date_value is not None and str(latest_signal_date_value).strip():
        latest_signal_date = pd.Timestamp(latest_signal_date_value).normalize()
        if pd.isna(latest_signal_date):
            raise ValueError("manifest latest_signal_date must parse as a date")

    return ModelSignalManifest(
        model_version=manifest_model_version,
        feature_set_version=(
            str(manifest["feature_set_version"]).strip()
            if manifest.get("feature_set_version") is not None
            else None
        ),
        label_horizon_days=_optional_int(
            manifest.get("label_horizon_days"),
            field_name="label_horizon_days",
        ),
        latest_signal_date=latest_signal_date,
        row_count=_optional_int(manifest.get("row_count"), field_name="row_count"),
        symbol_count=_optional_int(
            manifest.get("symbol_count"),
            field_name="symbol_count",
        ),
        export_created_at=(
            str(manifest["export_created_at"]).strip()
            if manifest.get("export_created_at") is not None
            else None
        ),
        candidate_id=(
            str(manifest["candidate_id"]).strip()
            if manifest.get("candidate_id") is not None
            else None
        ),
        artifact_path=(
            str(manifest["artifact_path"]).strip()
            if manifest.get("artifact_path") is not None
            else None
        ),
        status=status,
        warnings=_manifest_warnings(manifest.get("warnings")),
    )


def load_model_signal_manifest(
    path: str | Path,
    *,
    model_version: str,
    require_ready: bool = True,
) -> ModelSignalManifest:
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise ValueError(f"Model signal manifest path does not exist: {manifest_path}")
    if not manifest_path.is_file():
        raise ValueError(f"Model signal manifest path is not a file: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("Model signal manifest must be a JSON object")

    return validate_model_signal_manifest(
        manifest,
        model_version=model_version,
        require_ready=require_ready,
    )


def _candidate_manifest_paths_for_signal_file(path: Path) -> list[Path]:
    return [path.with_name(DEFAULT_MODEL_SIGNAL_MANIFEST_FILE_NAME)]


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

    def _local_model_version_paths(self, root: Path, model_version: str) -> list[Path]:
        version_dir = root / f"model_version={_normalize_model_version(model_version)}"
        preferred_path = version_dir / self.file_name
        if preferred_path.exists():
            return [preferred_path]
        if not version_dir.is_dir():
            return []
        return sorted(
            path
            for path in version_dir.rglob("*")
            if path.is_file() and _is_supported_model_signal_file(path)
        )

    def _local_paths(self, model_version: str | None) -> list[Path]:
        base = Path(self.base_path)
        if _has_glob_pattern(base):
            matches = [
                Path(path)
                for path in glob(str(base), recursive=True)
                if Path(path).is_file() and _is_supported_model_signal_file(path)
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
                daily_roots = (
                    base / "model_signals_daily",
                    base / "artifacts" / "model_signals_daily",
                )
                for daily_root in daily_roots:
                    matches = self._local_model_version_paths(daily_root, model_version)
                    if matches:
                        return matches

                version_path = Path(self.path_for_model_version(model_version))
                if version_path.exists():
                    return [version_path]
                matches = self._local_model_version_paths(base, model_version)
                if matches:
                    return matches

            matches = [
                path
                for path in base.rglob("*")
                if path.is_file() and _is_supported_model_signal_file(path)
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

    def manifest_path_for_model_version(self, model_version: str) -> str | Path:
        signal_path = self.path_for_model_version(model_version)
        if _is_uri(signal_path):
            return (
                str(signal_path).rsplit("/", 1)[0].rstrip("/")
                + f"/{DEFAULT_MODEL_SIGNAL_MANIFEST_FILE_NAME}"
            )
        return Path(signal_path).with_name(DEFAULT_MODEL_SIGNAL_MANIFEST_FILE_NAME)

    def load_manifest(
        self,
        *,
        model_version: str,
        require_ready: bool = True,
    ) -> ModelSignalManifest | None:
        """Load a sibling manifest when it is available for a local artifact."""

        if _is_uri(self.base_path):
            return None

        candidate_paths: list[Path] = []
        try:
            signal_paths = self._local_paths(model_version)
        except ValueError:
            signal_paths = []

        for signal_path in signal_paths:
            candidate_paths.extend(_candidate_manifest_paths_for_signal_file(signal_path))

        candidate_paths.append(Path(self.manifest_path_for_model_version(model_version)))

        seen: set[Path] = set()
        for path in candidate_paths:
            if path in seen:
                continue
            seen.add(path)
            if path.exists():
                return load_model_signal_manifest(
                    path,
                    model_version=model_version,
                    require_ready=require_ready,
                )
        return None

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
