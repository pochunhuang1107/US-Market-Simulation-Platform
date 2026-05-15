from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session

from market_simulator.data.model_signals import (
    ModelSignalManifest,
    ModelSignalRepository,
    validate_model_signal_frame,
)
from market_simulator.auth.current_user import CurrentUser
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.repositories.strategies import (
    get_strategy_for_user,
    get_strategy_version_for_user,
)
from market_simulator.services.model_signal_catalog import (
    get_model_signal_catalog_entry,
)
from market_simulator.services.model_signal_preview import (
    CURRENT_ARTIFACT_SOURCE_LABEL,
    ModelSignalArtifactSource,
    resolve_current_model_signal_data_path,
)
from market_simulator.settings import get_settings


class SavedStrategyCurrentSignalError(ValueError):
    code = "SAVED_STRATEGY_CURRENT_SIGNAL_ERROR"


class SavedStrategyCurrentSignalNotFoundError(SavedStrategyCurrentSignalError):
    code = "STRATEGY_NOT_FOUND"


class SavedStrategyCurrentSignalNotModelSignalError(SavedStrategyCurrentSignalError):
    code = "STRATEGY_NOT_MODEL_SIGNAL"


class SavedStrategyCurrentSignalArtifactNotFoundError(SavedStrategyCurrentSignalError):
    code = "MODEL_SIGNAL_ARTIFACT_NOT_FOUND"


class SavedStrategyCurrentSignalInvalidError(SavedStrategyCurrentSignalError):
    code = "SAVED_STRATEGY_CURRENT_SIGNAL_INVALID"


@dataclass(frozen=True)
class SavedStrategyCurrentSignalRequest:
    strategy_id: str | None = None
    strategy_version_id: str | None = None
    current_user: CurrentUser | dict[str, Any] | None = None
    as_of_date: str | date | pd.Timestamp | None = None
    data_path: str | None = None
    frame: pd.DataFrame | None = None
    manifest: ModelSignalManifest | None = None
    repository: ModelSignalRepository | None = None


def _user_id(current_user: CurrentUser | dict[str, Any] | None) -> str:
    if current_user is None:
        raise SavedStrategyCurrentSignalNotFoundError("Strategy not found")

    try:
        user_id = current_user["id"]
    except (KeyError, TypeError):
        user_id = getattr(current_user, "id", None)

    if not user_id:
        raise SavedStrategyCurrentSignalNotFoundError("Strategy not found")

    return str(user_id)


def _safe_missing_error() -> SavedStrategyCurrentSignalArtifactNotFoundError:
    return SavedStrategyCurrentSignalArtifactNotFoundError(
        "Model signal artifact is not configured or could not be found."
    )


def _safe_invalid_error(message: str) -> SavedStrategyCurrentSignalInvalidError:
    return SavedStrategyCurrentSignalInvalidError(
        f"Current model signal state could not be evaluated: {message}"
    )


def _parse_as_of_date(value: str | date | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.Timestamp(value).normalize()
    if pd.isna(parsed):
        raise _safe_invalid_error("as_of_date must parse as a date")
    return parsed


def _date_string(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


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


def _normalize_bucket_filter(bucket_filter: list[str] | None) -> set[str]:
    if not bucket_filter:
        return set()
    return {
        str(bucket).strip().lower()
        for bucket in bucket_filter
        if str(bucket).strip()
    }


def _target_weights(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    weight = round(1.0 / len(symbols), 10)
    weights = {symbol: weight for symbol in symbols}
    weights[symbols[-1]] = round(1.0 - sum(weights[s] for s in symbols[:-1]), 10)
    return weights


def _selected_rows_payload(
    rows: pd.DataFrame,
    *,
    ranking_field: str,
) -> list[dict[str, Any]]:
    optional_columns = (
        "score",
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
        if "signal_bucket" in row.index:
            item["bucket"] = _json_value(row["signal_bucket"])
        payload.append(item)
    return payload


def _load_strategy_and_version(
    db: Session,
    request: SavedStrategyCurrentSignalRequest,
    user_id: str,
):
    if request.strategy_version_id is not None:
        version = get_strategy_version_for_user(db, request.strategy_version_id, user_id)
        if version is None:
            raise SavedStrategyCurrentSignalNotFoundError("Strategy not found")
        strategy = version.strategy
        if request.strategy_id is not None and str(version.strategy_id) != str(
            request.strategy_id
        ):
            raise SavedStrategyCurrentSignalNotFoundError("Strategy not found")
        return strategy, version

    if request.strategy_id is None:
        raise SavedStrategyCurrentSignalNotFoundError("Strategy not found")

    strategy = get_strategy_for_user(db, request.strategy_id, user_id)
    if strategy is None or strategy.current_version_id is None:
        raise SavedStrategyCurrentSignalNotFoundError("Strategy not found")

    version = get_strategy_version_for_user(db, strategy.current_version_id, user_id)
    if version is None:
        raise SavedStrategyCurrentSignalNotFoundError("Strategy not found")

    return strategy, version


def _load_frame_and_manifest(
    request: SavedStrategyCurrentSignalRequest,
    *,
    model_version: str,
    universe: list[str],
    supported_universe: tuple[str, ...],
) -> tuple[pd.DataFrame, ModelSignalManifest | None, ModelSignalArtifactSource]:
    source = ModelSignalArtifactSource(CURRENT_ARTIFACT_SOURCE_LABEL)
    if request.frame is not None:
        try:
            return (
                validate_model_signal_frame(
                    request.frame,
                    supported_symbols=supported_universe,
                ),
                request.manifest,
                source,
            )
        except ValueError as exc:
            raise _safe_invalid_error(str(exc)) from exc

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
            supported_symbols=supported_universe,
            duckdb_database=settings.duckdb_database,
            s3_region=settings.s3_region,
        )

    try:
        frame = repository.load(model_version=model_version, universe=universe)
    except ValueError as exc:
        message = str(exc)
        if "does not exist" in message or "No model signal files" in message:
            raise _safe_missing_error() from exc
        raise _safe_invalid_error("Model signal artifact is invalid.") from exc

    manifest = request.manifest
    if manifest is None:
        try:
            manifest = repository.load_manifest(model_version=model_version)
        except ValueError as exc:
            raise _safe_invalid_error(str(exc)) from exc

    return frame, manifest, source


def evaluate_current_signal_for_saved_strategy(
    db: Session,
    request: SavedStrategyCurrentSignalRequest,
) -> dict[str, Any]:
    user_id = _user_id(request.current_user)
    strategy, version = _load_strategy_and_version(db, request, user_id)
    config = version.config_json or {}
    model_signal_config = config.get("model_signal") if isinstance(config, dict) else None
    if not isinstance(model_signal_config, dict) or model_signal_config.get("enabled") is not True:
        raise SavedStrategyCurrentSignalNotModelSignalError(
            "Saved strategy is not a model-signal strategy."
        )

    try:
        strategy_config = StrategyV2.model_validate(config)
    except ValidationError as exc:
        raise _safe_invalid_error(str(exc.errors()[0]["msg"])) from exc

    model_signal = strategy_config.model_signal
    if model_signal is None or not model_signal.enabled:
        raise SavedStrategyCurrentSignalNotModelSignalError(
            "Saved strategy is not a model-signal strategy."
        )

    entry = get_model_signal_catalog_entry(model_signal.model_version)
    if entry is None:
        raise _safe_invalid_error("Model signal is not registered or enabled.")

    as_of = _parse_as_of_date(request.as_of_date)
    signal_frame, manifest, source = _load_frame_and_manifest(
        request,
        model_version=model_signal.model_version,
        universe=model_signal.universe,
        supported_universe=entry.supported_universe,
    )

    filtered = signal_frame[
        (signal_frame["model_version"] == model_signal.model_version)
        & (signal_frame["symbol"].isin(model_signal.universe))
    ].copy()
    if as_of is not None:
        filtered = filtered[filtered["date"] <= as_of]

    ranking_field = model_signal.ranking_field
    if ranking_field not in signal_frame.columns:
        raise _safe_invalid_error(f"ranking_field '{ranking_field}' is missing")

    latest_signal_date = None
    latest_rows = filtered.iloc[0:0].copy()
    eligible = latest_rows.copy()
    if not filtered.empty:
        latest_signal_date = filtered["date"].max()
        latest_rows = filtered[filtered["date"] == latest_signal_date].copy()
        eligible = latest_rows.copy()

        bucket_filter = _normalize_bucket_filter(model_signal.signal_bucket_filter)
        if bucket_filter:
            if "signal_bucket" not in eligible.columns:
                eligible = eligible.iloc[0:0]
            else:
                artifact_bucket = (
                    eligible["signal_bucket"].astype(str).str.strip().str.lower()
                )
                eligible = eligible[artifact_bucket.isin(bucket_filter)]

        if model_signal.min_confidence is not None:
            if "confidence" not in eligible.columns:
                eligible = eligible.iloc[0:0]
            else:
                eligible = eligible[
                    eligible["confidence"].notna()
                    & (eligible["confidence"] >= model_signal.min_confidence)
                ]

        if not eligible.empty:
            eligible = eligible.copy()
            eligible[ranking_field] = pd.to_numeric(
                eligible[ranking_field],
                errors="coerce",
            )
            if eligible[ranking_field].isna().any():
                raise _safe_invalid_error(
                    f"ranking_field '{ranking_field}' must be numeric"
                )
            eligible = eligible.sort_values(
                by=[ranking_field, "symbol"],
                ascending=[False, True],
            )

    selected = eligible.head(model_signal.top_n or 0)
    selected_symbols = (
        selected["symbol"].astype(str).tolist() if not selected.empty else []
    )
    fallback_used = not selected_symbols
    fallback_type = model_signal.fallback.type if fallback_used else None
    fallback_symbol = (
        model_signal.fallback.symbol
        if fallback_used and model_signal.fallback.type == "asset"
        else None
    )

    if selected_symbols:
        target_weights = _target_weights(selected_symbols)
    elif fallback_symbol:
        selected_symbols = [fallback_symbol]
        target_weights = {fallback_symbol: 1.0}
    else:
        target_weights = {}

    manifest_payload = manifest.public_dict() if manifest else None
    return {
        "strategy_id": str(strategy.id),
        "strategy_version_id": str(version.id),
        "model_version": model_signal.model_version,
        "as_of_date": (
            _date_string(as_of)
            if as_of is not None
            else _date_string(latest_signal_date)
        ),
        "latest_signal_date": _date_string(latest_signal_date),
        "selected_symbols": selected_symbols,
        "target_weights": target_weights,
        "selected_rows": _selected_rows_payload(selected, ranking_field=ranking_field),
        "fallback_used": fallback_used,
        "fallback_type": fallback_type,
        "fallback_symbol": fallback_symbol,
        "ranking_field": ranking_field,
        "top_n": model_signal.top_n,
        "universe": list(model_signal.universe),
        "signal_bucket_filter": list(model_signal.signal_bucket_filter or []),
        "min_confidence": model_signal.min_confidence,
        "manifest_status": manifest.status if manifest else None,
        "manifest_warnings": list(manifest.warnings) if manifest else [],
        "export_created_at": manifest.export_created_at if manifest else None,
        "manifest": manifest_payload,
        "source": {
            "type": "model_signal_artifact",
            "label": source.label,
            "manifest_status": manifest.status if manifest else None,
        },
    }
