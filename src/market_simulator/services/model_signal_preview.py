from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from market_simulator.data.model_signals import (
    ModelSignalManifest,
    ModelSignalRepository,
    validate_model_signal_frame,
)
from market_simulator.services.model_signal_catalog import (
    ModelSignalCatalogEntry,
    get_model_signal_catalog_entry,
)
from market_simulator.settings import get_settings


class ModelSignalPreviewError(ValueError):
    code = "MODEL_SIGNAL_PREVIEW_ERROR"


class ModelSignalPreviewNotFoundError(ModelSignalPreviewError):
    code = "MODEL_SIGNAL_ARTIFACT_NOT_FOUND"


class ModelSignalPreviewInvalidError(ModelSignalPreviewError):
    code = "MODEL_SIGNAL_ARTIFACT_INVALID"


CURRENT_ARTIFACT_SOURCE_LABEL = "current artifact"
HISTORICAL_ARTIFACT_FALLBACK_SOURCE_LABEL = "historical artifact fallback"


@dataclass(frozen=True)
class ModelSignalPreviewRequest:
    model_version: str
    data_path: str | None = None
    frame: pd.DataFrame | None = None
    manifest: ModelSignalManifest | None = None
    repository: ModelSignalRepository | None = None


@dataclass(frozen=True)
class ModelSignalArtifactSource:
    label: str


def _safe_missing_error() -> ModelSignalPreviewNotFoundError:
    return ModelSignalPreviewNotFoundError(
        "Model signal artifact is not configured or could not be found."
    )


def _safe_invalid_error(message: str) -> ModelSignalPreviewInvalidError:
    return ModelSignalPreviewInvalidError(f"Model signal artifact is invalid: {message}")


def resolve_current_model_signal_data_path(
    *,
    data_path: str | None = None,
) -> tuple[str, ModelSignalArtifactSource]:
    if data_path is not None:
        return data_path, ModelSignalArtifactSource(CURRENT_ARTIFACT_SOURCE_LABEL)

    settings = get_settings()
    current_data_path = settings.model_signal_current_data_path.strip()
    if current_data_path:
        return current_data_path, ModelSignalArtifactSource(CURRENT_ARTIFACT_SOURCE_LABEL)

    return (
        settings.model_signal_data_path,
        ModelSignalArtifactSource(HISTORICAL_ARTIFACT_FALLBACK_SOURCE_LABEL),
    )


def _load_frame_and_manifest(
    request: ModelSignalPreviewRequest,
    entry: ModelSignalCatalogEntry,
) -> tuple[pd.DataFrame, ModelSignalManifest | None, ModelSignalArtifactSource]:
    source = ModelSignalArtifactSource(CURRENT_ARTIFACT_SOURCE_LABEL)
    if request.frame is not None:
        try:
            frame = validate_model_signal_frame(
                request.frame,
                supported_symbols=entry.supported_universe,
            )
        except ValueError as exc:
            raise _safe_invalid_error(str(exc)) from exc
        return frame, request.manifest, source

    repository = request.repository
    if repository is None:
        settings = get_settings()
        data_path, source = resolve_current_model_signal_data_path(
            data_path=request.data_path,
        )
        if not data_path or not data_path.strip():
            raise _safe_missing_error()
        repository = ModelSignalRepository(
            data_path,
            supported_symbols=entry.supported_universe,
            duckdb_database=settings.duckdb_database,
            s3_region=settings.s3_region,
        )

    try:
        frame = repository.load(model_version=entry.model_version)
    except ValueError as exc:
        message = str(exc)
        if "does not exist" in message or "No model signal files" in message:
            raise _safe_missing_error() from exc
        raise _safe_invalid_error(message) from exc

    manifest = request.manifest
    if manifest is None:
        try:
            manifest = repository.load_manifest(model_version=entry.model_version)
        except ValueError as exc:
            raise _safe_invalid_error(str(exc)) from exc

    return frame, manifest, source


def _normalize_bucket_filter(bucket_filter: Iterable[str]) -> set[str]:
    return {
        str(bucket).strip().lower()
        for bucket in bucket_filter
        if str(bucket).strip()
    }


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _date_string(value: Any) -> str:
    return pd.Timestamp(value).date().isoformat()


def _generated_at(
    latest_rows: pd.DataFrame,
    manifest: ModelSignalManifest | None,
) -> str | None:
    if manifest and manifest.export_created_at:
        return manifest.export_created_at
    if "created_at" not in latest_rows.columns:
        return None

    created_at = pd.to_datetime(latest_rows["created_at"], errors="coerce").dropna()
    if created_at.empty:
        return None
    return created_at.max().isoformat()


def _selected_rows_payload(
    rows: pd.DataFrame,
    *,
    ranking_field: str,
) -> list[dict[str, Any]]:
    optional_columns = (
        ranking_field,
        "rank",
        "predicted_return",
        "confidence",
        "signal_bucket",
    )
    payload: list[dict[str, Any]] = []
    for selection_rank, (_, row) in enumerate(rows.iterrows(), start=1):
        item: dict[str, Any] = {
            "symbol": str(row["symbol"]),
            "date": _date_string(row["date"]),
            "selection_rank": selection_rank,
        }
        for column in optional_columns:
            if column in row.index:
                item[column] = _json_value(row[column])
        payload.append(item)
    return payload


def _select_latest_signal_rows(
    signal_frame: pd.DataFrame,
    entry: ModelSignalCatalogEntry,
) -> tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame, int, int]:
    latest_signal_date = signal_frame["date"].max()
    latest_rows = signal_frame[signal_frame["date"] == latest_signal_date].copy()
    row_count_latest_date = int(len(latest_rows))
    universe_symbol_count = int(latest_rows["symbol"].nunique())

    eligible = latest_rows
    bucket_filter = _normalize_bucket_filter(entry.default_signal_bucket_filter)
    if bucket_filter:
        if "signal_bucket" not in eligible.columns:
            raise _safe_invalid_error("signal_bucket is required by registry defaults")
        artifact_bucket = eligible["signal_bucket"].astype(str).str.strip().str.lower()
        eligible = eligible[artifact_bucket.isin(bucket_filter)]

    ranking_field = entry.ranking_field
    eligible = eligible.copy()
    eligible[ranking_field] = pd.to_numeric(eligible[ranking_field], errors="coerce")
    if eligible[ranking_field].isna().any():
        raise _safe_invalid_error(f"ranking_field '{ranking_field}' must be numeric")

    ranked = eligible.sort_values(
        by=[ranking_field, "symbol"],
        ascending=[False, True],
    )
    return (
        latest_signal_date,
        latest_rows,
        ranked.head(entry.default_top_n),
        row_count_latest_date,
        universe_symbol_count,
    )


def preview_current_model_signal(
    model_version: str,
    *,
    data_path: str | None = None,
    frame: pd.DataFrame | None = None,
    manifest: ModelSignalManifest | None = None,
    repository: ModelSignalRepository | None = None,
) -> dict[str, Any]:
    entry = get_model_signal_catalog_entry(model_version)
    if entry is None:
        raise ModelSignalPreviewNotFoundError(
            "Model signal is not registered or enabled."
        )

    request = ModelSignalPreviewRequest(
        model_version=model_version,
        data_path=data_path,
        frame=frame,
        manifest=manifest,
        repository=repository,
    )
    signal_frame, loaded_manifest, source = _load_frame_and_manifest(request, entry)
    signal_frame = signal_frame[
        signal_frame["model_version"] == entry.model_version
    ].copy()
    if signal_frame.empty:
        raise ModelSignalPreviewNotFoundError(
            "No model signal rows were found for the requested model."
        )

    ranking_field = entry.ranking_field
    if ranking_field not in signal_frame.columns:
        raise _safe_invalid_error(f"ranking_field '{ranking_field}' is missing")

    (
        latest_signal_date,
        latest_rows,
        selected,
        row_count_latest_date,
        universe_symbol_count,
    ) = _select_latest_signal_rows(
        signal_frame,
        entry,
    )

    manifest_payload = loaded_manifest.public_dict() if loaded_manifest else None
    return {
        "model_version": entry.model_version,
        "latest_signal_date": _date_string(latest_signal_date),
        "selected_symbols": selected["symbol"].astype(str).tolist(),
        "selected_rows": _selected_rows_payload(
            selected,
            ranking_field=ranking_field,
        ),
        "universe_symbol_count": universe_symbol_count,
        "row_count_latest_date": row_count_latest_date,
        "ranking_field": ranking_field,
        "top_n": entry.default_top_n,
        "signal_bucket_filter": list(entry.default_signal_bucket_filter),
        "manifest_status": loaded_manifest.status if loaded_manifest else None,
        "manifest_warnings": list(loaded_manifest.warnings) if loaded_manifest else [],
        "export_created_at": (
            loaded_manifest.export_created_at if loaded_manifest else None
        ),
        "generated_at": _generated_at(latest_rows, loaded_manifest),
        "manifest": manifest_payload,
        "source": {
            "type": "model_signal_artifact",
            "label": source.label,
            "manifest_status": loaded_manifest.status if loaded_manifest else None,
        },
    }
