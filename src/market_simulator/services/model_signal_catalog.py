from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from market_simulator.data.model_signals import DEFAULT_MODEL_SIGNAL_PATH_TEMPLATE
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.settings import get_settings


LINEAR_SMOOTH10_MARGIN002_UNIVERSE = (
    "ARKK",
    "DIA",
    "GLD",
    "HYG",
    "IBIT",
    "IEF",
    "IWM",
    "LQD",
    "MTUM",
    "QQQ",
    "QUAL",
    "SLV",
    "SPY",
    "TLT",
    "VTI",
    "VTV",
    "VUG",
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)


@dataclass(frozen=True)
class ModelSignalFallbackDefault:
    type: Literal["cash", "asset"] = "cash"
    symbol: str | None = None

    def as_config(self) -> dict[str, str]:
        config = {"type": self.type}
        if self.symbol:
            config["symbol"] = self.symbol
        return config


@dataclass(frozen=True)
class ModelSignalCatalogEntry:
    model_version: str
    display_name: str
    description: str
    family: str
    research_status: str
    supported_universe: tuple[str, ...]
    default_universe: tuple[str, ...]
    ranking_field: str
    allowed_ranking_fields: tuple[str, ...]
    default_top_n: int
    default_signal_bucket_filter: tuple[str, ...]
    default_fallback: ModelSignalFallbackDefault
    default_benchmark: str
    default_tradable_symbol: str
    label_horizon_days: int
    feature_set_version: str
    artifact_path_setting: str
    artifact_path_hint: str
    risk_notes: tuple[str, ...]
    limitations: tuple[str, ...]
    recommended_use: str
    created_at: str
    updated_at: str
    enabled: bool = True

    def recommended_defaults(self) -> dict[str, Any]:
        return {
            "universe": list(self.default_universe),
            "ranking_field": self.ranking_field,
            "top_n": self.default_top_n,
            "signal_bucket_filter": list(self.default_signal_bucket_filter),
            "fallback": self.default_fallback.as_config(),
            "benchmark": self.default_benchmark,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "display_name": self.display_name,
            "description": self.description,
            "family": self.family,
            "research_status": self.research_status,
            "supported_universe": list(self.supported_universe),
            "default_universe": list(self.default_universe),
            "ranking_field": self.ranking_field,
            "allowed_ranking_fields": list(self.allowed_ranking_fields),
            "default_top_n": self.default_top_n,
            "default_signal_bucket_filter": list(self.default_signal_bucket_filter),
            "default_fallback": self.default_fallback.as_config(),
            "default_benchmark": self.default_benchmark,
            "label_horizon_days": self.label_horizon_days,
            "feature_set_version": self.feature_set_version,
            "artifact_path_setting": self.artifact_path_setting,
            "artifact_path_hint": self.artifact_path_hint,
            "risk_notes": list(self.risk_notes),
            "limitations": list(self.limitations),
            "recommended_use": self.recommended_use,
            "recommended_defaults": self.recommended_defaults(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "enabled": self.enabled,
        }


MODEL_SIGNAL_REGISTRY: dict[str, ModelSignalCatalogEntry] = {
    "linear_smooth10_margin002_v1": ModelSignalCatalogEntry(
        model_version="linear_smooth10_margin002_v1",
        display_name="Linear Smooth 10 Margin 0.002",
        description=(
            "Research-exported linear model signal strategy using the default "
            "feature set and a 20 trading-day label horizon."
        ),
        family="linear_model_signal",
        research_status="paper_tracking",
        supported_universe=LINEAR_SMOOTH10_MARGIN002_UNIVERSE,
        default_universe=LINEAR_SMOOTH10_MARGIN002_UNIVERSE,
        ranking_field="score",
        allowed_ranking_fields=("score",),
        default_top_n=1,
        default_signal_bucket_filter=("top",),
        default_fallback=ModelSignalFallbackDefault(type="cash"),
        default_benchmark="SPY",
        default_tradable_symbol="QQQ",
        label_horizon_days=20,
        feature_set_version="default_features_v1",
        artifact_path_setting="MODEL_SIGNAL_DATA_PATH",
        artifact_path_hint=DEFAULT_MODEL_SIGNAL_PATH_TEMPLATE.replace(
            "<VERSION>",
            "linear_smooth10_margin002_v1",
        ),
        risk_notes=(
            "Top-1 selection is concentrated and can rotate into a single ETF.",
            "This is a research and paper-tracking candidate only.",
            "Volatile contributors include XLE, IBIT, ARKK, SLV, and QQQ.",
            "This is not investment advice and is not a guaranteed signal.",
        ),
        limitations=(
            "No live inference is performed by the platform.",
            "The registry does not contain model artifacts or training code.",
            "Results depend on separately managed point-in-time model signal artifacts.",
            "Research status does not imply future performance.",
        ),
        recommended_use=(
            "Use for controlled backend simulations and paper-tracking reviews "
            "after validating the matching model signal artifact."
        ),
        created_at="2026-05-13",
        updated_at="2026-05-13",
        enabled=True,
    )
}


class ModelSignalCatalogError(ValueError):
    pass


def list_model_signal_catalog(
    *,
    include_disabled: bool = False,
) -> list[ModelSignalCatalogEntry]:
    entries = sorted(MODEL_SIGNAL_REGISTRY.values(), key=lambda entry: entry.display_name)
    if include_disabled:
        return entries
    return [entry for entry in entries if entry.enabled]


def get_model_signal_catalog_entry(
    model_version: str,
    *,
    include_disabled: bool = False,
) -> ModelSignalCatalogEntry | None:
    entry = MODEL_SIGNAL_REGISTRY.get(model_version.strip())
    if entry is None:
        return None
    if not include_disabled and not entry.enabled:
        return None
    return entry


def _normalize_universe(universe: list[str] | tuple[str, ...]) -> list[str]:
    normalized = []
    seen = set()
    for symbol in universe:
        value = str(symbol).strip().upper()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _normalize_fallback(
    fallback: str | dict[str, Any] | None,
    default_fallback: ModelSignalFallbackDefault,
) -> dict[str, str]:
    if fallback is None:
        return default_fallback.as_config()

    if isinstance(fallback, str):
        value = fallback.strip().upper()
        if not value or value.lower() == "cash":
            return {"type": "cash"}
        return {"type": "asset", "symbol": value}

    fallback_type = str(fallback.get("type", "cash")).strip().lower()
    if fallback_type == "cash":
        return {"type": "cash"}
    if fallback_type == "asset":
        symbol = str(fallback.get("symbol", "")).strip().upper()
        if not symbol:
            raise ModelSignalCatalogError("fallback symbol is required for asset fallback")
        return {"type": "asset", "symbol": symbol}

    raise ModelSignalCatalogError("fallback type must be cash or asset")


def _validate_supported_symbol(symbol: str, *, field_name: str) -> None:
    supported = set(get_settings().supported_etf_symbols)
    if symbol not in supported:
        raise ModelSignalCatalogError(f"{field_name} symbol is not supported: {symbol}")


def build_model_signal_strategy_config(
    *,
    model_version: str,
    start_date: str | date,
    end_date: str | date,
    universe: list[str] | tuple[str, ...] | None = None,
    top_n: int | None = None,
    fallback: str | dict[str, Any] | None = None,
    benchmark: str | None = None,
    ranking_field: str | None = None,
    signal_bucket_filter: list[str] | tuple[str, ...] | str | None = None,
    min_confidence: float | None = None,
    name: str | None = None,
    initial_capital: float = 100_000.0,
    transaction_cost_bps: float = 5.0,
) -> dict[str, Any]:
    entry = get_model_signal_catalog_entry(model_version)
    if entry is None:
        raise ModelSignalCatalogError(f"model signal is not registered or enabled: {model_version}")

    selected_universe = _normalize_universe(
        entry.default_universe if universe is None else universe
    )
    if not selected_universe:
        raise ModelSignalCatalogError("universe must include at least one symbol")

    unsupported = sorted(set(selected_universe) - set(entry.supported_universe))
    if unsupported:
        raise ModelSignalCatalogError(
            "universe contains symbols unsupported by this model: "
            f"{', '.join(unsupported)}"
        )

    selected_ranking_field = (ranking_field or entry.ranking_field).strip()
    if selected_ranking_field not in entry.allowed_ranking_fields:
        raise ModelSignalCatalogError(
            "ranking_field is not allowed for this model: "
            f"{selected_ranking_field}"
        )

    selected_top_n = top_n if top_n is not None else entry.default_top_n
    if selected_top_n < 1:
        raise ModelSignalCatalogError("top_n must be at least 1")
    if selected_top_n > len(selected_universe):
        raise ModelSignalCatalogError("top_n cannot exceed selected universe size")

    selected_fallback = _normalize_fallback(fallback, entry.default_fallback)
    if selected_fallback["type"] == "asset":
        _validate_supported_symbol(selected_fallback["symbol"], field_name="fallback")

    selected_benchmark = (benchmark or entry.default_benchmark).strip().upper()
    _validate_supported_symbol(selected_benchmark, field_name="benchmark")

    if signal_bucket_filter is None:
        bucket_filter = list(entry.default_signal_bucket_filter)
    elif isinstance(signal_bucket_filter, str):
        bucket_filter = [signal_bucket_filter]
    else:
        bucket_filter = list(signal_bucket_filter)
    bucket_filter = [bucket.strip() for bucket in bucket_filter if bucket and bucket.strip()]

    tradable_symbol = (
        entry.default_tradable_symbol
        if entry.default_tradable_symbol in selected_universe
        else selected_universe[0]
    )

    model_signal: dict[str, Any] = {
        "enabled": True,
        "model_version": entry.model_version,
        "ranking_field": selected_ranking_field,
        "universe": selected_universe,
        "top_n": selected_top_n,
        "rebalance": {
            "frequency": "monthly",
            "day": "first_trading_day",
        },
        "fallback": selected_fallback,
    }
    if bucket_filter:
        model_signal["signal_bucket_filter"] = bucket_filter
    if min_confidence is not None:
        model_signal["min_confidence"] = min_confidence

    config = {
        "schema_version": "2.0",
        "name": name or f"{entry.model_version}-model-signal",
        "tradable_symbol": tradable_symbol,
        "benchmark_symbol": selected_benchmark,
        "reference_symbols": sorted(
            set(selected_universe + [selected_benchmark]) - {tradable_symbol}
        ),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "initial_capital": initial_capital,
        "transaction_cost_bps": transaction_cost_bps,
        "model_signal": model_signal,
    }

    StrategyV2.model_validate(config)
    return config
