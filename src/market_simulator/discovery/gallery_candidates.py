from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from copy import deepcopy
from typing import Any, Callable, Iterable, Literal

import pandas as pd

from market_simulator.data.repository import MarketDataBundle, MarketDataRepository
from market_simulator.engine.runner import run_simulation
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.settings import get_settings


DEFAULT_OUTPUT_DIR = Path("data/discovery_reports")
DEFAULT_CACHE_DIR = Path("data/discovery_reports/cache")
DEFAULT_INITIAL_CAPITAL = 100_000
DEFAULT_TRANSACTION_COST_BPS = 5
EVALUATION_SCHEMA_VERSION = "gallery_discovery_v4_rotation_equal_weight"
TOP_CONFIG_COUNT = 25
MIN_MEANINGFUL_TRADES = 2
MAX_REASONABLE_TRADES = 120
MAX_DRAWDOWN_WORSE_THAN_BENCHMARK_PCT = -5.0
RECENT_ALPHA_GALLERY_FLOOR_PCT = -1.0
RECENT_ALPHA_WATCHLIST_FLOOR_PCT = -8.0
ALPHA_WATCHLIST_FLOOR_PCT = -2.0
DRAWDOWN_WATCHLIST_IMPROVEMENT_PCT = 5.0
DEFENSIVE_DRAWDOWN_IMPROVEMENT_PCT = 8.0
SearchMode = Literal["smoke", "standard", "broad", "refine"]


@dataclass(frozen=True)
class CandidateConfig:
    candidate_id: str
    family: str
    config_summary: str
    config: dict[str, Any]
    config_hash: str = ""


@dataclass(frozen=True)
class PeriodSpec:
    label: str
    start_date: str
    end_date: str


class _MarketDataLoader:
    def __init__(self, repo: MarketDataRepository):
        self.repo = repo
        self._symbol_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._bundle_cache: dict[tuple[str, tuple[str, ...], str, str], MarketDataBundle] = {}
        self.symbol_frame_cache_hits = 0
        self.symbol_frame_cache_misses = 0
        self.bundle_cache_hits = 0
        self.bundle_cache_misses = 0

    def get_symbol_frame(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        key = (symbol.upper(), start_date, end_date)
        if key in self._symbol_cache:
            self.symbol_frame_cache_hits += 1
        else:
            self.symbol_frame_cache_misses += 1
            self._symbol_cache[key] = self.repo.get_market_data(
                tradable_symbol=symbol,
                reference_symbols=[],
                start_date=start_date,
                end_date=end_date,
            ).tradable
        return self._symbol_cache[key].copy()

    def _bundle_key(self, strategy: StrategyV2) -> tuple[str, tuple[str, ...], str, str]:
        reference_symbols = (
            strategy.rotation_required_reference_symbols()
            if getattr(getattr(strategy, "rotation", None), "enabled", False)
            else strategy.reference_symbols
        )
        return (
            strategy.tradable_symbol.upper(),
            tuple(sorted(symbol.upper() for symbol in reference_symbols)),
            str(strategy.start_date),
            str(strategy.end_date),
        )

    def get_bundle(self, strategy: StrategyV2) -> MarketDataBundle:
        key = self._bundle_key(strategy)
        if key in self._bundle_cache:
            self.bundle_cache_hits += 1
        else:
            self.bundle_cache_misses += 1
            self._bundle_cache[key] = self.repo.get_market_data(
                tradable_symbol=key[0],
                reference_symbols=list(key[1]),
                start_date=key[2],
                end_date=key[3],
            )
        # run_simulation calls enrich_market_data, which copies bundle dataframes
        # before adding indicators, so the cached raw bundle can be reused directly.
        return self._bundle_cache[key]

    def cache_stats(self) -> dict[str, int]:
        return {
            "bundle_cache_hits": self.bundle_cache_hits,
            "bundle_cache_misses": self.bundle_cache_misses,
            "symbol_frame_cache_hits": self.symbol_frame_cache_hits,
            "symbol_frame_cache_misses": self.symbol_frame_cache_misses,
        }


def _slug(*parts: object) -> str:
    cleaned = []
    for part in parts:
        value = str(part).lower().replace("/", "-").replace("_", "-")
        value = "".join(ch if ch.isalnum() else "-" for ch in value)
        cleaned.append("-".join(piece for piece in value.split("-") if piece))
    return "-".join(piece for piece in cleaned if piece)


def _canonical_config(config: dict[str, Any]) -> dict[str, Any]:
    canonical = deepcopy(config)
    canonical.pop("name", None)
    return canonical


def _hash_config(config: dict[str, Any], *, include_name: bool = True) -> str:
    payload = config if include_name else _canonical_config(config)
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _atomic(rule_type: str, **kwargs: Any) -> dict[str, Any]:
    return {"kind": "atomic", "type": rule_type, **kwargs}


def _group(operator: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "group", "operator": operator, "rules": rules}


def _not(rule: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "not", "rule": rule}


def _base_config(
    *,
    name: str,
    tradable_symbol: str,
    benchmark_symbol: str,
    reference_symbols: Iterable[str],
    start_date: str,
    end_date: str,
    stop_loss_pct: float | None = 0.08,
    core_allocation_pct: float = 0.0,
    scale_in_fraction: float = 1.0,
    max_position_pct: float = 1.0,
    max_scale_in_steps: int | None = 1,
    min_bars_between_scale_ins: int = 0,
    cooldown_bars: int = 0,
) -> dict[str, Any]:
    reference_symbol_list = sorted({symbol.upper() for symbol in reference_symbols})
    return {
        "schema_version": "2.0",
        "name": name,
        "tradable_symbol": tradable_symbol,
        "benchmark_symbol": benchmark_symbol,
        "reference_symbols": reference_symbol_list,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": DEFAULT_INITIAL_CAPITAL,
        "transaction_cost_bps": DEFAULT_TRANSACTION_COST_BPS,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": max_position_pct,
        },
        "entry_rule": _atomic("rsi_below", symbol=tradable_symbol, lookback=14, threshold=30),
        "exit_rule": _atomic("rsi_above", symbol=tradable_symbol, lookback=14, threshold=65),
        "risk": {
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": None,
            "partial_take_profit": None,
            "cooldown_bars": cooldown_bars,
        },
        "core_overlay": {
            "enabled": core_allocation_pct > 0,
            "core_allocation_pct": core_allocation_pct,
        },
        "position_management": {
            "scale_in_fraction": scale_in_fraction,
            "exit_behavior": "sell_all",
            "profit_reduce_threshold": None,
            "max_scale_in_steps": max_scale_in_steps,
            "min_bars_between_scale_ins": min_bars_between_scale_ins,
            "scale_in_requires_persistent_signal": min_bars_between_scale_ins > 0,
            "minimum_trade_notional": 500,
        },
    }


def _rotation_config(
    *,
    name: str,
    tradable_symbol: str,
    benchmark_symbol: str,
    universe: list[str],
    start_date: str,
    end_date: str,
    lookback: int,
    top_n: int,
    rebalance_frequency: str = "monthly",
    fallback: dict[str, Any] | None = None,
    risk_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reference_symbols = sorted(
        {
            *[symbol.upper() for symbol in universe if symbol.upper() != tradable_symbol.upper()],
            benchmark_symbol.upper(),
            *(
                [str(fallback["symbol"]).upper()]
                if fallback and fallback.get("type") == "asset" and fallback.get("symbol")
                else []
            ),
        }
    )
    return {
        "schema_version": "2.0",
        "name": name,
        "tradable_symbol": tradable_symbol,
        "benchmark_symbol": benchmark_symbol,
        "reference_symbols": reference_symbols,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": DEFAULT_INITIAL_CAPITAL,
        "transaction_cost_bps": DEFAULT_TRANSACTION_COST_BPS,
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "partial_take_profit": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
        "rotation": {
            "enabled": True,
            "universe": [symbol.upper() for symbol in universe],
            "ranking": {
                "type": "relative_return",
                "lookback": lookback,
                "descending": True,
            },
            "rebalance": {
                "frequency": rebalance_frequency,
                "day": "first_trading_day",
            },
            "selection": {
                "top_n": top_n,
            },
            "allocation": {
                "weighting": "equal_weight",
                "max_position_pct": 1.0,
            },
            "risk_filter": risk_filter,
            "fallback": fallback or {"type": "cash"},
        },
    }


def _is_supported(
    *,
    tradable_symbol: str,
    benchmark_symbol: str,
    reference_symbols: Iterable[str],
    supported_etfs: set[str],
    supported_reference_series: set[str],
) -> bool:
    if tradable_symbol.upper() not in supported_etfs:
        return False
    if benchmark_symbol.upper() not in supported_etfs:
        return False
    supported_references = supported_etfs | supported_reference_series
    return all(symbol.upper() in supported_references for symbol in reference_symbols)


def _candidate(
    *,
    family: str,
    config_summary: str,
    config: dict[str, Any],
) -> CandidateConfig:
    config_hash = _hash_config(config, include_name=False)
    candidate_id = f"{_slug(family, config['name'])}-{config_hash[:8]}"
    StrategyV2.model_validate(config)
    return CandidateConfig(
        candidate_id=candidate_id,
        family=family,
        config_summary=config_summary,
        config=config,
        config_hash=config_hash,
    )


def _maybe_add(
    candidates: list[CandidateConfig],
    *,
    family: str,
    config_summary: str,
    config: dict[str, Any],
    supported_etfs: set[str],
    supported_reference_series: set[str],
) -> None:
    if not _is_supported(
        tradable_symbol=config["tradable_symbol"],
        benchmark_symbol=config["benchmark_symbol"],
        reference_symbols=config.get("reference_symbols", []),
        supported_etfs=supported_etfs,
        supported_reference_series=supported_reference_series,
    ):
        return
    candidates.append(_candidate(family=family, config_summary=config_summary, config=config))


def dedupe_candidate_configs(candidates: Iterable[CandidateConfig]) -> list[CandidateConfig]:
    seen: set[str] = set()
    deduped: list[CandidateConfig] = []
    for candidate in candidates:
        config_hash = candidate.config_hash or _hash_config(candidate.config, include_name=False)
        if config_hash in seen:
            continue
        seen.add(config_hash)
        if candidate.config_hash:
            deduped.append(candidate)
        else:
            deduped.append(
                CandidateConfig(
                    candidate_id=candidate.candidate_id,
                    family=candidate.family,
                    config_summary=candidate.config_summary,
                    config=candidate.config,
                    config_hash=config_hash,
                )
            )
    return deduped


def select_candidates_for_run(
    candidates: list[CandidateConfig],
    *,
    max_candidates: int | None,
) -> list[CandidateConfig]:
    if max_candidates is None:
        return candidates
    return candidates[:max_candidates]


def _supported_symbols(symbols: Iterable[str], supported_etfs: set[str]) -> list[str]:
    seen: set[str] = set()
    filtered: list[str] = []
    for symbol in symbols:
        normalized = symbol.upper()
        if normalized in supported_etfs and normalized not in seen:
            seen.add(normalized)
            filtered.append(normalized)
    return filtered


def _rotation_fallback_variants(supported_etfs: set[str], *, mode: SearchMode) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [{"type": "cash"}]
    if mode == "smoke":
        return variants
    for symbol in ("TLT", "IEF"):
        if symbol in supported_etfs:
            variants.append({"type": "asset", "symbol": symbol})
    return variants


def _rotation_risk_filter_variants(supported_etfs: set[str], *, mode: SearchMode) -> list[tuple[str, dict[str, Any] | None]]:
    variants: list[tuple[str, dict[str, Any] | None]] = [("no_filter", None)]
    if "SPY" not in supported_etfs or mode == "smoke":
        return variants
    variants.append(
        (
            "spy_sma200",
            _atomic("sma_above", symbol="SPY", fast_window=1, slow_window=200),
        )
    )
    if mode == "broad":
        variants.append(
            (
                "spy_sma100",
                _atomic("sma_above", symbol="SPY", fast_window=1, slow_window=100),
            )
        )
    return variants


def _rotation_universe_specs(
    *,
    mode: SearchMode,
    supported_etfs: set[str],
) -> list[tuple[str, str, str, list[str]]]:
    sector_universe = _supported_symbols(
        ["XLK", "XLY", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE"],
        supported_etfs,
    )
    broad_universe = _supported_symbols(
        ["SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "IEF", "HYG", "LQD", "XLK", "XLY", "XLV"],
        supported_etfs,
    )
    specs = [
        (
            "asset_rotation_momentum",
            "Growth/rate ETF mix",
            "QQQ",
            _supported_symbols(["QQQ", "SPY", "XLK", "TLT"], supported_etfs),
        ),
        (
            "asset_rotation_momentum",
            "Growth/sector/rate ETF mix",
            "QQQ",
            _supported_symbols(["QQQ", "SPY", "XLK", "XLY", "XLV", "TLT"], supported_etfs),
        ),
        (
            "sector_rotation_momentum",
            "Sector ETF mix",
            "XLK",
            sector_universe,
        ),
        (
            "defensive_rotation_momentum",
            "Defensive cross-asset mix",
            "QQQ",
            _supported_symbols(["QQQ", "SPY", "TLT", "IEF", "GLD"], supported_etfs),
        ),
    ]
    if mode == "broad":
        specs.append(
            (
                "asset_rotation_momentum",
                "Broad supported ETF mix",
                "SPY",
                broad_universe,
            )
        )

    valid_specs: list[tuple[str, str, str, list[str]]] = []
    for family, label, tradable_symbol, universe in specs:
        if tradable_symbol not in supported_etfs and universe:
            tradable_symbol = universe[0]
        if len(universe) >= 2 and tradable_symbol in universe:
            valid_specs.append((family, label, tradable_symbol, universe))
    return valid_specs


def _rotation_grid(mode: SearchMode, supported_etfs: set[str]) -> list[dict[str, Any]]:
    lookbacks = [63] if mode == "smoke" else [63, 126]
    top_ns = [1, 2] if mode != "smoke" else [1]
    rebalance_frequencies = ["monthly"]
    fallback_variants = _rotation_fallback_variants(supported_etfs, mode=mode)
    risk_filter_variants = _rotation_risk_filter_variants(supported_etfs, mode=mode)
    risk_fallback_pairs = [
        (risk_label, risk_filter, fallback)
        for risk_label, risk_filter in risk_filter_variants
        for fallback in fallback_variants
    ]

    if mode == "broad":
        lookbacks = [21, 63, 126, 252]
        top_ns = [1, 2, 3]
        rebalance_frequencies = ["monthly", "quarterly"]
        risk_filter_by_label = dict(risk_filter_variants)
        fallback_by_label = {
            fallback.get("symbol", "cash").lower(): fallback
            for fallback in fallback_variants
        }
        desired_pairs = [
            ("no_filter", "cash"),
            ("spy_sma200", "cash"),
            ("spy_sma200", "tlt"),
            ("spy_sma100", "cash"),
            ("spy_sma100", "ief"),
        ]
        risk_fallback_pairs = [
            (risk_label, risk_filter_by_label[risk_label], fallback_by_label[fallback_label])
            for risk_label, fallback_label in desired_pairs
            if risk_label in risk_filter_by_label and fallback_label in fallback_by_label
        ]

    grid: list[dict[str, Any]] = []
    for lookback in lookbacks:
        for top_n in top_ns:
            for rebalance_frequency in rebalance_frequencies:
                for risk_label, risk_filter, fallback in risk_fallback_pairs:
                    if mode != "broad" and fallback.get("type") == "asset" and risk_filter is None:
                        continue
                    grid.append(
                        {
                            "lookback": lookback,
                            "top_n": top_n,
                            "rebalance_frequency": rebalance_frequency,
                            "risk_label": risk_label,
                            "risk_filter": risk_filter,
                            "fallback": fallback,
                        }
                    )
    return grid


def _mode_values(mode: SearchMode) -> dict[str, Any]:
    if mode == "smoke":
        return {
            "rsi_symbols": ["QQQ"],
            "core_symbols": ["QQQ"],
            "trend_symbols": ["QQQ"],
            "sector_symbols": ["XLK"],
            "sma_pairs": [(50, 200)],
            "trend_windows": [200],
            "rsi_entries": [35],
            "rsi_exits": [60],
            "vix_entries": [20],
            "vix_exits": [35],
            "defensive_windows": [90],
            "sector_windows": [60],
            "sector_thresholds": [0.01],
            "core_allocations": [0.65],
            "risk_variants": [(None, 0, 1.0)],
            "position_variants": [(1.0, 1.0), (0.33, 0.75)],
        }
    if mode == "broad":
        return {
            "rsi_symbols": ["QQQ", "SPY", "IWM", "XLK", "XLY", "XLF", "XLE", "XLV"],
            "core_symbols": ["QQQ", "SPY", "XLK", "XLY"],
            "trend_symbols": ["QQQ", "SPY", "IWM", "XLK", "XLY", "XLF", "XLE", "XLV"],
            "sector_symbols": ["XLK", "XLY", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE"],
            "sma_pairs": [(20, 100), (50, 150), (50, 200), (100, 200)],
            "trend_windows": [100, 150, 200],
            "rsi_entries": [30, 35, 40, 45],
            "rsi_exits": [55, 60, 65, 70],
            "vix_entries": [15, 20, 25, 30],
            "vix_exits": [30, 35, 40, 45],
            "defensive_windows": [60, 90, 120],
            "sector_windows": [30, 60, 90, 120],
            "sector_thresholds": [0.0, 0.01, 0.03, 0.05],
            "core_allocations": [0.5, 0.65, 0.8],
            "risk_variants": [(None, 0, 1.0), (0.08, 3, 1.0), (0.12, 5, 0.75), (0.15, 10, 0.5)],
            "position_variants": [(1.0, 1.0), (0.5, 0.75), (0.33, 0.75)],
        }
    return {
        "rsi_symbols": ["QQQ", "SPY", "IWM"],
        "core_symbols": ["QQQ", "SPY"],
        "trend_symbols": ["QQQ", "SPY", "IWM"],
        "sector_symbols": ["XLK", "XLY", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB", "XLRE"],
        "sma_pairs": [(20, 100), (50, 200)],
        "trend_windows": [100, 200],
        "rsi_entries": [30, 35, 40],
        "rsi_exits": [55, 60, 65],
        "vix_entries": [15, 20, 25],
        "vix_exits": [30, 35, 40],
        "defensive_windows": [60, 120],
        "sector_windows": [60, 120],
        "sector_thresholds": [0.0, 0.01, 0.03],
        "core_allocations": [0.5, 0.65, 0.8],
        "risk_variants": [(None, 0, 1.0), (0.08, 3, 1.0)],
        "position_variants": [(1.0, 1.0), (0.33, 0.75)],
    }


def generate_candidate_configs(
    *,
    start_date: str,
    end_date: str,
    mode: SearchMode = "standard",
    refine_input: Path | None = None,
    supported_etfs: Iterable[str] | None = None,
    supported_reference_series: Iterable[str] | None = None,
) -> list[CandidateConfig]:
    settings = get_settings()
    etfs = {symbol.upper() for symbol in (supported_etfs or settings.supported_etf_symbols)}
    reference_series = {
        symbol.upper()
        for symbol in (supported_reference_series or settings.supported_reference_series_symbols)
    }
    values = _mode_values("standard" if mode == "refine" else mode)
    candidates: list[CandidateConfig] = []

    def add_candidate(family: str, summary: str, config: dict[str, Any]) -> None:
        _maybe_add(
            candidates,
            family=family,
            config_summary=summary,
            config=config,
            supported_etfs=etfs,
            supported_reference_series=reference_series,
        )

    if mode == "refine" and refine_input and refine_input.exists():
        payload = json.loads(refine_input.read_text(encoding="utf-8"))
        raw_configs: list[dict[str, Any]] = []
        if isinstance(payload, list):
            raw_configs = [item.get("config", item) for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            for key in ("gallery_ready_outperformance", "gallery_ready_defensive", "watchlist_candidates", "results"):
                value = payload.get(key, [])
                if isinstance(value, list):
                    raw_configs.extend(
                        item.get("config", item) for item in value if isinstance(item, dict)
                    )

        for idx, config in enumerate(raw_configs[:200], start=1):
            try:
                base = StrategyV2.model_validate(config).model_dump(mode="json", exclude_none=True)
            except Exception:
                continue
            base["start_date"] = start_date
            base["end_date"] = end_date
            add_candidate(
                "refine_seed",
                f"Refine seed from {refine_input.name}",
                {**base, "name": f"{base['name']} Refine Seed {idx}"},
            )
            for stop_loss_pct, cooldown_bars, max_position_pct in [(None, 0, 1.0), (0.08, 3, 0.75), (0.12, 5, 0.5)]:
                variant = deepcopy(base)
                variant["name"] = f"{base['name']} Refine Risk {stop_loss_pct} {cooldown_bars} {max_position_pct}"
                variant["risk"]["stop_loss_pct"] = stop_loss_pct
                variant["risk"]["cooldown_bars"] = cooldown_bars
                variant["allocation"]["max_position_pct"] = max_position_pct
                add_candidate(
                    "refine_risk_controls",
                    f"Refine risk variant stop={stop_loss_pct}, cooldown={cooldown_bars}, max={max_position_pct:.0%}",
                    variant,
                )

        return dedupe_candidate_configs(candidates)

    for symbol in values["rsi_symbols"]:
        for entry_threshold in values["rsi_entries"]:
            for exit_threshold in values["rsi_exits"]:
                if exit_threshold <= entry_threshold + 10:
                    continue
                for stop_loss_pct, cooldown_bars, max_position_pct in values["risk_variants"]:
                    config = _base_config(
                        name=f"{symbol} RSI {entry_threshold} {exit_threshold} stop {stop_loss_pct} cd {cooldown_bars} max {max_position_pct}",
                        tradable_symbol=symbol,
                        benchmark_symbol=symbol,
                        reference_symbols=[],
                        start_date=start_date,
                        end_date=end_date,
                        stop_loss_pct=stop_loss_pct,
                        scale_in_fraction=0.25,
                        max_position_pct=max_position_pct,
                        max_scale_in_steps=3,
                        min_bars_between_scale_ins=3,
                        cooldown_bars=cooldown_bars,
                    )
                    config["entry_rule"] = _atomic(
                        "rsi_below",
                        symbol=symbol,
                        lookback=14,
                        threshold=entry_threshold,
                    )
                    config["exit_rule"] = _atomic(
                        "rsi_above",
                        symbol=symbol,
                        lookback=14,
                        threshold=exit_threshold,
                    )
                    add_candidate(
                        "rsi_mean_reversion",
                        (
                            f"{symbol} RSI(14) entry < {entry_threshold}, exit > {exit_threshold}, "
                            f"25% scale-ins, stop={stop_loss_pct}, cooldown={cooldown_bars}, max={max_position_pct:.0%}"
                        ),
                        config,
                    )

    for symbol in ["QQQ", "SPY"]:
        for rsi_entry in values["rsi_entries"]:
            for rsi_exit in values["rsi_exits"]:
                if rsi_exit <= rsi_entry + 10:
                    continue
                for vix_entry in values["vix_entries"]:
                    for vix_exit in values["vix_exits"]:
                        if vix_exit <= vix_entry:
                            continue
                        if mode != "broad" and (vix_entry, vix_exit) not in {(15, 30), (20, 35), (25, 40)}:
                            continue
                        for stop_loss_pct, cooldown_bars, max_position_pct in values["risk_variants"][:2]:
                            config = _base_config(
                                name=f"{symbol} RSI VIX {rsi_entry} {rsi_exit} {vix_entry} {vix_exit} stop {stop_loss_pct}",
                                tradable_symbol=symbol,
                                benchmark_symbol=symbol,
                                reference_symbols=["VIX"],
                                start_date=start_date,
                                end_date=end_date,
                                stop_loss_pct=stop_loss_pct,
                                scale_in_fraction=0.25,
                                max_position_pct=max_position_pct,
                                max_scale_in_steps=3,
                                min_bars_between_scale_ins=3,
                                cooldown_bars=cooldown_bars,
                            )
                            config["entry_rule"] = _group(
                                "AND",
                                [
                                    _atomic("series_below", symbol="VIX", threshold=vix_entry),
                                    _atomic("rsi_below", symbol=symbol, lookback=14, threshold=rsi_entry),
                                ],
                            )
                            config["exit_rule"] = _group(
                                "OR",
                                [
                                    _atomic("series_above", symbol="VIX", threshold=vix_exit),
                                    _atomic("rsi_above", symbol=symbol, lookback=14, threshold=rsi_exit),
                                ],
                            )
                            add_candidate(
                                "rsi_vix_regime_filter",
                                (
                                    f"{symbol} RSI pullback with VIX < {vix_entry} entry "
                                    f"and VIX > {vix_exit} exit"
                                ),
                                config,
                            )

    for symbol in values["trend_symbols"]:
        for fast_window, slow_window in values["sma_pairs"]:
            for stop_loss_pct, cooldown_bars, max_position_pct in values["risk_variants"]:
                config = _base_config(
                    name=f"{symbol} SMA {fast_window} {slow_window} stop {stop_loss_pct} cd {cooldown_bars} max {max_position_pct}",
                    tradable_symbol=symbol,
                    benchmark_symbol=symbol,
                    reference_symbols=[],
                    start_date=start_date,
                    end_date=end_date,
                    stop_loss_pct=stop_loss_pct,
                    scale_in_fraction=1.0,
                    max_position_pct=max_position_pct,
                    max_scale_in_steps=1,
                    cooldown_bars=cooldown_bars,
                )
                config["entry_rule"] = _atomic(
                    "sma_above",
                    symbol=symbol,
                    fast_window=fast_window,
                    slow_window=slow_window,
                )
                config["exit_rule"] = _atomic(
                    "sma_cross_below",
                    symbol=symbol,
                    fast_window=fast_window,
                    slow_window=slow_window,
                )
                add_candidate(
                    "sma_trend_filter",
                    f"{symbol} SMA {fast_window}/{slow_window} trend state, max={max_position_pct:.0%}",
                    config,
                )

    for symbol in values["core_symbols"]:
        for core_allocation_pct in values["core_allocations"]:
            for slow_window in values["trend_windows"]:
                for vix_entry in values["vix_entries"]:
                    if mode != "broad" and vix_entry not in {20, 25}:
                        continue
                    config = _base_config(
                        name=f"{symbol} Core VIX SMA {slow_window} {vix_entry} core {core_allocation_pct}",
                        tradable_symbol=symbol,
                        benchmark_symbol=symbol,
                        reference_symbols=["VIX"],
                        start_date=start_date,
                        end_date=end_date,
                        stop_loss_pct=None,
                        core_allocation_pct=core_allocation_pct,
                        scale_in_fraction=1.0,
                        max_scale_in_steps=1,
                    )
                    config["entry_rule"] = _group(
                        "AND",
                        [
                            _atomic("series_below", symbol="VIX", threshold=vix_entry),
                            _atomic("sma_above", symbol=symbol, fast_window=1, slow_window=slow_window),
                        ],
                    )
                    config["exit_rule"] = _atomic(
                        "sma_cross_below",
                        symbol=symbol,
                        fast_window=1,
                        slow_window=slow_window,
                    )
                    add_candidate(
                        "core_vix_trend_overlay",
                        (
                            f"{symbol} {core_allocation_pct:.0%} core plus overlay when "
                            f"price > SMA({slow_window}) and VIX < {vix_entry}; trend exit"
                        ),
                        config,
                    )

            for rsi_entry in values["rsi_entries"]:
                for rsi_exit in values["rsi_exits"]:
                    if rsi_exit <= rsi_entry + 10:
                        continue
                    config = _base_config(
                        name=f"{symbol} Core RSI Overlay {rsi_entry} {rsi_exit} core {core_allocation_pct}",
                        tradable_symbol=symbol,
                        benchmark_symbol=symbol,
                        reference_symbols=[],
                        start_date=start_date,
                        end_date=end_date,
                        stop_loss_pct=None,
                        core_allocation_pct=core_allocation_pct,
                        scale_in_fraction=0.5,
                        max_scale_in_steps=2,
                        min_bars_between_scale_ins=3,
                    )
                    config["entry_rule"] = _atomic(
                        "rsi_below",
                        symbol=symbol,
                        lookback=14,
                        threshold=rsi_entry,
                    )
                    config["exit_rule"] = _atomic(
                        "rsi_above",
                        symbol=symbol,
                        lookback=14,
                        threshold=rsi_exit,
                    )
                    add_candidate(
                        "core_rsi_overlay",
                        (
                            f"{symbol} {core_allocation_pct:.0%} core plus RSI overlay "
                            f"entry < {rsi_entry}, exit > {rsi_exit}"
                        ),
                        config,
                    )

    for symbol in values["trend_symbols"]:
        for slow_window in values["trend_windows"]:
            for rsi_entry in values["rsi_entries"]:
                for rsi_exit in values["rsi_exits"]:
                    if rsi_exit <= rsi_entry + 10:
                        continue
                    for scale_in_fraction, max_position_pct in values["position_variants"]:
                        config = _base_config(
                            name=f"{symbol} Trend Pullback {slow_window} {rsi_entry} {rsi_exit} scale {scale_in_fraction} max {max_position_pct}",
                            tradable_symbol=symbol,
                            benchmark_symbol=symbol,
                            reference_symbols=[],
                            start_date=start_date,
                            end_date=end_date,
                            scale_in_fraction=scale_in_fraction,
                            max_position_pct=max_position_pct,
                            max_scale_in_steps=3,
                            min_bars_between_scale_ins=3,
                        )
                        config["entry_rule"] = _group(
                            "AND",
                            [
                                _atomic("sma_above", symbol=symbol, fast_window=1, slow_window=slow_window),
                                _atomic("rsi_below", symbol=symbol, lookback=14, threshold=rsi_entry),
                            ],
                        )
                        config["exit_rule"] = _group(
                            "OR",
                            [
                                _atomic("rsi_above", symbol=symbol, lookback=14, threshold=rsi_exit),
                                _atomic("sma_cross_below", symbol=symbol, fast_window=1, slow_window=slow_window),
                            ],
                        )
                        add_candidate(
                            "trend_pullback",
                            (
                                f"{symbol} pullback entries only above SMA({slow_window}); "
                                f"RSI < {rsi_entry}, exit RSI > {rsi_exit} or trend break"
                            ),
                            config,
                        )

    for symbol in ["QQQ", "SPY"]:
        for slow_window in values["trend_windows"]:
            for vix_entry in values["vix_entries"]:
                config = _base_config(
                    name=f"{symbol} VIX Trend {slow_window} {vix_entry}",
                    tradable_symbol=symbol,
                    benchmark_symbol=symbol,
                    reference_symbols=["VIX"],
                    start_date=start_date,
                    end_date=end_date,
                    scale_in_fraction=1.0,
                    max_scale_in_steps=1,
                )
                config["entry_rule"] = _group(
                    "AND",
                    [
                        _atomic("sma_above", symbol=symbol, fast_window=1, slow_window=slow_window),
                        _atomic("series_below", symbol="VIX", threshold=vix_entry),
                    ],
                )
                config["exit_rule"] = _atomic(
                    "sma_cross_below",
                    symbol=symbol,
                    fast_window=1,
                    slow_window=slow_window,
                )
                add_candidate(
                    "vix_trend_filter",
                    (
                        f"{symbol} trend entries only when VIX < {vix_entry}; "
                        f"exit on SMA({slow_window}) trend break"
                    ),
                    config,
                )

    for symbol in ["QQQ", "SPY"]:
        for slow_window in values["trend_windows"]:
            for vix_entry in values["vix_entries"]:
                for vix_exit in values["vix_exits"]:
                    if vix_exit <= vix_entry:
                        continue
                    config = _base_config(
                        name=f"{symbol} VIX Risk On Off {slow_window} {vix_entry} {vix_exit}",
                        tradable_symbol=symbol,
                        benchmark_symbol=symbol,
                        reference_symbols=["VIX"],
                        start_date=start_date,
                        end_date=end_date,
                        scale_in_fraction=1.0,
                        max_scale_in_steps=1,
                    )
                    config["entry_rule"] = _group(
                        "AND",
                        [
                            _atomic("sma_above", symbol=symbol, fast_window=1, slow_window=slow_window),
                            _atomic("series_below", symbol="VIX", threshold=vix_entry),
                        ],
                    )
                    config["exit_rule"] = _group(
                        "OR",
                        [
                            _atomic("sma_cross_below", symbol=symbol, fast_window=1, slow_window=slow_window),
                            _atomic("series_above", symbol="VIX", threshold=vix_exit),
                        ],
                    )
                    add_candidate(
                        "vix_risk_on_off",
                        f"{symbol} trend/VIX risk-on entries, exit on VIX > {vix_exit} or trend break",
                        config,
                    )

    for defensive_symbol in ["TLT", "IEF"]:
        for lookback in values["defensive_windows"]:
            for threshold in ([-0.01, 0.0, 0.01] if mode == "broad" else [-0.01, 0.0]):
                config = _base_config(
                    name=f"QQQ {defensive_symbol} Relative Strength {lookback} {threshold}",
                    tradable_symbol="QQQ",
                    benchmark_symbol="QQQ",
                    reference_symbols=[defensive_symbol],
                    start_date=start_date,
                    end_date=end_date,
                    scale_in_fraction=1.0,
                    max_scale_in_steps=1,
                )
                rule = _atomic(
                    "relative_return_above",
                    symbol="QQQ",
                    reference_symbol=defensive_symbol,
                    lookback=lookback,
                    threshold=threshold,
                )
                config["entry_rule"] = rule
                config["exit_rule"] = _not(rule.copy())
                add_candidate(
                    "defensive_relative_strength",
                    (
                        f"QQQ when it leads {defensive_symbol} by more than "
                        f"{threshold:.0%} over {lookback} days"
                    ),
                    config,
                )

    for rsi_entry in [35, 40]:
        for rsi_exit in [60, 65]:
            if rsi_exit <= rsi_entry + 10:
                continue
            for slow_window in [90, 120, 150] if mode == "broad" else [100, 150]:
                defensive_symbol = "IEF"
                config = _base_config(
                    name=f"QQQ IEF Trend Pullback {rsi_entry} {rsi_exit} {slow_window}",
                    tradable_symbol="QQQ",
                    benchmark_symbol="QQQ",
                    reference_symbols=[defensive_symbol],
                    start_date=start_date,
                    end_date=end_date,
                    scale_in_fraction=0.25,
                    max_scale_in_steps=3,
                    min_bars_between_scale_ins=3,
                )
                config["entry_rule"] = _group(
                    "AND",
                    [
                        _atomic("rsi_below", symbol="QQQ", lookback=14, threshold=rsi_entry),
                        _atomic("sma_above", symbol=defensive_symbol, fast_window=1, slow_window=slow_window),
                    ],
                )
                config["exit_rule"] = _group(
                    "OR",
                    [
                        _atomic("rsi_above", symbol="QQQ", lookback=14, threshold=rsi_exit),
                        _atomic("sma_cross_below", symbol=defensive_symbol, fast_window=1, slow_window=slow_window),
                    ],
                )
                add_candidate(
                    "defensive_trend_filtered_pullback",
                    f"QQQ RSI entry < {rsi_entry} with IEF above SMA({slow_window})",
                    config,
                )

    for sector_symbol in values["sector_symbols"]:
        for lookback in values["sector_windows"]:
            for threshold in values["sector_thresholds"]:
                config = _base_config(
                    name=f"{sector_symbol} SPY Relative Strength {lookback} {threshold}",
                    tradable_symbol=sector_symbol,
                    benchmark_symbol="SPY",
                    reference_symbols=["SPY"],
                    start_date=start_date,
                    end_date=end_date,
                    scale_in_fraction=1.0,
                    max_scale_in_steps=1,
                )
                rule = _atomic(
                    "relative_return_above",
                    symbol=sector_symbol,
                    reference_symbol="SPY",
                    lookback=lookback,
                    threshold=threshold,
                )
                config["entry_rule"] = rule
                config["exit_rule"] = _not(rule.copy())
                add_candidate(
                    "sector_relative_strength",
                    (
                        f"{sector_symbol} vs SPY relative return > {threshold:.0%} "
                        f"over {lookback} days"
                    ),
                    config,
                )

            for core_allocation_pct in values["core_allocations"] if mode == "broad" else [0.5]:
                config = _base_config(
                    name=f"{sector_symbol} SPY Core Relative Strength {lookback} core {core_allocation_pct}",
                    tradable_symbol=sector_symbol,
                    benchmark_symbol="SPY",
                    reference_symbols=["SPY"],
                    start_date=start_date,
                    end_date=end_date,
                    stop_loss_pct=None,
                    core_allocation_pct=core_allocation_pct,
                    scale_in_fraction=1.0,
                    max_scale_in_steps=1,
                )
                rule = _atomic(
                    "relative_return_above",
                    symbol=sector_symbol,
                    reference_symbol="SPY",
                    lookback=lookback,
                    threshold=0.0,
                )
                config["entry_rule"] = rule
                config["exit_rule"] = _not(rule.copy())
                add_candidate(
                    "sector_core_relative_strength",
                    f"{sector_symbol} {core_allocation_pct:.0%} core plus overlay when it leads SPY over {lookback} days",
                    config,
                )

    for symbol in ["QQQ", "SPY"]:
        vol_grid = [(20, 0.20, 0.30), (20, 0.25, 0.35), (60, 0.20, 0.30)]
        if mode == "broad":
            vol_grid.extend([(60, 0.25, 0.35), (90, 0.20, 0.30)])
        for lookback, vol_entry, vol_exit in vol_grid:
            config = _base_config(
                name=f"{symbol} RSI Realized Vol {lookback} {vol_entry}",
                tradable_symbol=symbol,
                benchmark_symbol=symbol,
                reference_symbols=[],
                start_date=start_date,
                end_date=end_date,
                scale_in_fraction=0.25,
                max_scale_in_steps=3,
                min_bars_between_scale_ins=3,
            )
            config["entry_rule"] = _group(
                "AND",
                [
                    _atomic("rsi_below", symbol=symbol, lookback=14, threshold=35),
                    _atomic("realized_volatility_below", symbol=symbol, lookback=lookback, threshold=vol_entry),
                ],
            )
            config["exit_rule"] = _group(
                "OR",
                [
                    _atomic("rsi_above", symbol=symbol, lookback=14, threshold=65),
                    _atomic("realized_volatility_above", symbol=symbol, lookback=lookback, threshold=vol_exit),
                ],
            )
            add_candidate(
                "realized_volatility_filter",
                f"{symbol} RSI pullback only when {lookback}d realized vol < {vol_entry:.0%}",
                config,
            )

    for family, universe_label, tradable_symbol, universe in _rotation_universe_specs(
        mode=mode,
        supported_etfs=etfs,
    ):
        for variant in _rotation_grid(mode, etfs):
            top_n = int(variant["top_n"])
            if top_n > len(universe):
                continue
            fallback = variant["fallback"]
            fallback_label = fallback.get("symbol", "cash").lower()
            risk_label = str(variant["risk_label"])
            rebalance_frequency = str(variant["rebalance_frequency"])
            lookback = int(variant["lookback"])
            name = (
                f"{universe_label} Rotation Top {top_n} {lookback} "
                f"{rebalance_frequency} {risk_label} fallback {fallback_label}"
            )
            config = _rotation_config(
                name=name,
                tradable_symbol=tradable_symbol,
                benchmark_symbol="SPY",
                universe=universe,
                start_date=start_date,
                end_date=end_date,
                lookback=lookback,
                top_n=top_n,
                rebalance_frequency=rebalance_frequency,
                risk_filter=variant["risk_filter"],
                fallback=fallback,
            )
            add_candidate(
                family,
                (
                    f"{universe_label}: {rebalance_frequency} top-{top_n} relative momentum, "
                    f"{lookback}d lookback, risk={risk_label}, fallback={fallback_label}"
                ),
                config,
            )

    return dedupe_candidate_configs(candidates)


def build_split_periods(start_date: str, end_date: str) -> list[PeriodSpec]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start >= end:
        raise ValueError("start_date must be earlier than end_date")

    total_days = (end - start).days
    split = start + timedelta(days=max(1, int(total_days * 0.65)))
    if split >= end:
        split = start + timedelta(days=max(1, total_days // 2))

    recent_start = split + timedelta(days=1)
    if recent_start >= end:
        recent_start = split

    return [
        PeriodSpec("full", start.isoformat(), end.isoformat()),
        PeriodSpec("earlier", start.isoformat(), split.isoformat()),
        PeriodSpec("recent_holdout", recent_start.isoformat(), end.isoformat()),
    ]


def max_drawdown_pct_from_equity(equity: Iterable[float]) -> float | None:
    series = pd.Series(list(equity), dtype="float64").dropna()
    if series.empty:
        return None
    running_max = series.cummax()
    drawdowns = (series / running_max) - 1.0
    return round(float(drawdowns.min()) * 100, 4)


def _buy_hold_metrics(
    loader: _MarketDataLoader,
    *,
    symbol: str,
    start_date: str,
    end_date: str,
) -> dict[str, float | None]:
    frame = loader.get_symbol_frame(
        symbol,
        start_date,
        end_date,
    )
    first_close = float(frame["close"].iloc[0])
    last_close = float(frame["close"].iloc[-1])
    return_pct = round(((last_close / first_close) - 1.0) * 100, 4)
    max_drawdown_pct = max_drawdown_pct_from_equity(frame["close"])
    return {
        "return_pct": return_pct,
        "max_drawdown_pct": max_drawdown_pct,
    }


def _universe_equal_weight_buy_hold_metrics(
    loader: _MarketDataLoader,
    *,
    universe: Iterable[str],
    start_date: str,
    end_date: str,
) -> dict[str, float | None]:
    symbols = sorted({symbol.upper() for symbol in universe if symbol})
    if not symbols:
        return {"return_pct": None, "max_drawdown_pct": None}

    close_frames: list[pd.DataFrame] = []
    for symbol in symbols:
        frame = loader.get_symbol_frame(symbol, start_date, end_date)[["date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.rename(columns={"close": symbol})
        close_frames.append(frame)

    merged = close_frames[0]
    for frame in close_frames[1:]:
        merged = merged.merge(frame, on="date", how="inner")
    merged = merged.sort_values("date")
    if merged.empty:
        return {"return_pct": None, "max_drawdown_pct": None}

    prices = merged[symbols].astype("float64").dropna()
    if prices.empty:
        return {"return_pct": None, "max_drawdown_pct": None}

    normalized = prices / prices.iloc[0]
    equal_weight_equity = normalized.mean(axis=1)
    return_pct = round((float(equal_weight_equity.iloc[-1]) - 1.0) * 100, 4)
    max_drawdown_pct = max_drawdown_pct_from_equity(equal_weight_equity)
    return {
        "return_pct": return_pct,
        "max_drawdown_pct": max_drawdown_pct,
    }


def _benchmark_metrics(loader: _MarketDataLoader, strategy: StrategyV2) -> dict[str, float | None]:
    return _buy_hold_metrics(
        loader,
        symbol=strategy.benchmark_symbol,
        start_date=str(strategy.start_date),
        end_date=str(strategy.end_date),
    )


def score_dual_benchmark_metrics(
    *,
    strategy_return_pct: float,
    strategy_max_drawdown_pct: float,
    tradable_buy_hold_return_pct: float,
    tradable_buy_hold_max_drawdown_pct: float | None,
    market_benchmark_symbol: str | None = None,
    market_benchmark_return_pct: float | None = None,
    market_benchmark_max_drawdown_pct: float | None = None,
    universe_equal_weight_buy_hold_return_pct: float | None = None,
    universe_equal_weight_buy_hold_max_drawdown_pct: float | None = None,
) -> dict[str, Any]:
    alpha_vs_tradable = round(strategy_return_pct - tradable_buy_hold_return_pct, 4)
    drawdown_delta_vs_tradable = (
        round(strategy_max_drawdown_pct - tradable_buy_hold_max_drawdown_pct, 4)
        if tradable_buy_hold_max_drawdown_pct is not None
        else None
    )
    alpha_vs_market = (
        round(strategy_return_pct - market_benchmark_return_pct, 4)
        if market_benchmark_return_pct is not None
        else None
    )
    drawdown_delta_vs_market = (
        round(strategy_max_drawdown_pct - market_benchmark_max_drawdown_pct, 4)
        if market_benchmark_max_drawdown_pct is not None
        else None
    )
    alpha_vs_universe_equal_weight = (
        round(strategy_return_pct - universe_equal_weight_buy_hold_return_pct, 4)
        if universe_equal_weight_buy_hold_return_pct is not None
        else None
    )
    drawdown_delta_vs_universe_equal_weight = (
        round(strategy_max_drawdown_pct - universe_equal_weight_buy_hold_max_drawdown_pct, 4)
        if universe_equal_weight_buy_hold_max_drawdown_pct is not None
        else None
    )
    return {
        "strategy_return_pct": strategy_return_pct,
        "tradable_buy_hold_return_pct": tradable_buy_hold_return_pct,
        "alpha_vs_tradable_buy_hold_pct": alpha_vs_tradable,
        "tradable_buy_hold_max_drawdown_pct": tradable_buy_hold_max_drawdown_pct,
        "drawdown_delta_vs_tradable_buy_hold_pct": drawdown_delta_vs_tradable,
        "market_benchmark_symbol": market_benchmark_symbol,
        "market_benchmark_return_pct": market_benchmark_return_pct,
        "alpha_vs_market_benchmark_pct": alpha_vs_market,
        "market_benchmark_max_drawdown_pct": market_benchmark_max_drawdown_pct,
        "drawdown_delta_vs_market_benchmark_pct": drawdown_delta_vs_market,
        "universe_equal_weight_buy_hold_return_pct": universe_equal_weight_buy_hold_return_pct,
        "universe_equal_weight_buy_hold_max_drawdown_pct": universe_equal_weight_buy_hold_max_drawdown_pct,
        "alpha_vs_universe_equal_weight_pct": alpha_vs_universe_equal_weight,
        "drawdown_delta_vs_universe_equal_weight_pct": drawdown_delta_vs_universe_equal_weight,
    }


def _period_benchmark_metrics(loader: _MarketDataLoader, strategy: StrategyV2) -> dict[str, Any]:
    start_date = str(strategy.start_date)
    end_date = str(strategy.end_date)
    tradable = _buy_hold_metrics(
        loader,
        symbol=strategy.tradable_symbol,
        start_date=start_date,
        end_date=end_date,
    )
    market_symbol = strategy.benchmark_symbol
    market = _buy_hold_metrics(
        loader,
        symbol=market_symbol,
        start_date=start_date,
        end_date=end_date,
    )
    universe = {"return_pct": None, "max_drawdown_pct": None}
    if getattr(getattr(strategy, "rotation", None), "enabled", False):
        universe = _universe_equal_weight_buy_hold_metrics(
            loader,
            universe=strategy.rotation.universe,
            start_date=start_date,
            end_date=end_date,
        )
    return {
        "tradable_buy_hold_return_pct": tradable["return_pct"],
        "tradable_buy_hold_max_drawdown_pct": tradable["max_drawdown_pct"],
        "market_benchmark_symbol": market_symbol,
        "market_benchmark_return_pct": market["return_pct"],
        "market_benchmark_max_drawdown_pct": market["max_drawdown_pct"],
        "universe_equal_weight_buy_hold_return_pct": universe["return_pct"],
        "universe_equal_weight_buy_hold_max_drawdown_pct": universe["max_drawdown_pct"],
    }


def _evaluate_period(
    *,
    candidate: CandidateConfig,
    period: PeriodSpec,
    loader: _MarketDataLoader,
) -> dict[str, Any]:
    config = dict(candidate.config)
    config["start_date"] = period.start_date
    config["end_date"] = period.end_date
    config["name"] = f"{candidate.config['name']} {period.label}"
    strategy = StrategyV2.model_validate(config)
    result = run_simulation(loader.get_bundle(strategy), strategy)

    summary = dict(result.summary)
    benchmark_inputs = _period_benchmark_metrics(loader, strategy)
    dual_metrics = score_dual_benchmark_metrics(
        strategy_return_pct=float(summary["total_return_pct"]),
        strategy_max_drawdown_pct=float(summary["max_drawdown_pct"]),
        tradable_buy_hold_return_pct=float(benchmark_inputs["tradable_buy_hold_return_pct"]),
        tradable_buy_hold_max_drawdown_pct=benchmark_inputs["tradable_buy_hold_max_drawdown_pct"],
        market_benchmark_symbol=str(benchmark_inputs["market_benchmark_symbol"]),
        market_benchmark_return_pct=float(benchmark_inputs["market_benchmark_return_pct"]),
        market_benchmark_max_drawdown_pct=benchmark_inputs["market_benchmark_max_drawdown_pct"],
        universe_equal_weight_buy_hold_return_pct=benchmark_inputs[
            "universe_equal_weight_buy_hold_return_pct"
        ],
        universe_equal_weight_buy_hold_max_drawdown_pct=benchmark_inputs[
            "universe_equal_weight_buy_hold_max_drawdown_pct"
        ],
    )
    summary.update(dual_metrics)
    if getattr(getattr(strategy, "rotation", None), "enabled", False):
        summary["rebalance_count"] = int(
            sum(1 for row in result.timeline if row.get("rebalance"))
        )
    summary["benchmark_return_pct"] = dual_metrics["market_benchmark_return_pct"]
    summary["alpha_vs_benchmark_pct"] = dual_metrics["alpha_vs_market_benchmark_pct"]
    summary["benchmark_max_drawdown_pct"] = dual_metrics["market_benchmark_max_drawdown_pct"]
    summary["drawdown_delta_vs_benchmark_pct"] = dual_metrics["drawdown_delta_vs_market_benchmark_pct"]
    summary["period_label"] = period.label
    return summary


def _metric_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    return float(value)


def _first_metric(payload: dict[str, Any], keys: Iterable[str], default: float = 0.0) -> float:
    for key in keys:
        value = _metric_float(payload, key)
        if value is not None:
            return value
    return default


def _best_metric(payload: dict[str, Any], keys: Iterable[str], default: float = 0.0) -> float:
    values = [
        value
        for key in keys
        if (value := _metric_float(payload, key)) is not None
    ]
    if not values:
        return default
    return max(values)


def _uses_rotation_benchmark(full_period: dict[str, Any]) -> bool:
    return full_period.get("alpha_vs_universe_equal_weight_pct") is not None


def build_candidate_flags(
    *,
    full_period: dict[str, Any],
    earlier_period: dict[str, Any],
    recent_period: dict[str, Any],
    max_drawdown_limit_pct: float = -35.0,
    min_trade_count: int = MIN_MEANINGFUL_TRADES,
    max_trade_count: int = MAX_REASONABLE_TRADES,
) -> dict[str, Any]:
    use_rotation_benchmark = _uses_rotation_benchmark(full_period)
    if use_rotation_benchmark:
        full_alpha = _first_metric(
            full_period,
            [
                "alpha_vs_universe_equal_weight_pct",
                "alpha_vs_market_benchmark_pct",
                "alpha_vs_tradable_buy_hold_pct",
                "alpha_vs_benchmark_pct",
            ],
        )
        earlier_alpha = _best_metric(
            earlier_period,
            [
                "alpha_vs_universe_equal_weight_pct",
                "alpha_vs_market_benchmark_pct",
                "alpha_vs_tradable_buy_hold_pct",
                "alpha_vs_benchmark_pct",
            ],
        )
        recent_alpha = _best_metric(
            recent_period,
            [
                "alpha_vs_universe_equal_weight_pct",
                "alpha_vs_market_benchmark_pct",
                "alpha_vs_tradable_buy_hold_pct",
                "alpha_vs_benchmark_pct",
            ],
        )
        drawdown_delta = full_period.get(
            "drawdown_delta_vs_universe_equal_weight_pct",
            full_period.get(
                "drawdown_delta_vs_market_benchmark_pct",
                full_period.get("drawdown_delta_vs_tradable_buy_hold_pct"),
            ),
        )
        benchmark_comparison_basis = "universe_equal_weight"
    else:
        full_alpha = _first_metric(
            full_period,
            ["alpha_vs_tradable_buy_hold_pct", "alpha_vs_benchmark_pct"],
        )
        earlier_alpha = _first_metric(
            earlier_period,
            ["alpha_vs_tradable_buy_hold_pct", "alpha_vs_benchmark_pct"],
        )
        recent_alpha = _first_metric(
            recent_period,
            ["alpha_vs_tradable_buy_hold_pct", "alpha_vs_benchmark_pct"],
        )
        drawdown_delta = full_period.get(
            "drawdown_delta_vs_tradable_buy_hold_pct",
            full_period.get("drawdown_delta_vs_benchmark_pct"),
        )
        benchmark_comparison_basis = "tradable_buy_hold"
    max_drawdown = float(full_period.get("max_drawdown_pct", 0) or 0)
    trade_count = int(
        full_period.get("rebalance_count", full_period.get("trade_count", 0)) or 0
    )
    sharpe = float(full_period.get("sharpe_ratio", 0) or 0)
    cagr = float(full_period.get("cagr_pct", 0) or 0)

    alpha_positive = full_alpha > 0
    recent_alpha_positive = recent_alpha >= 0
    full_period_outperforms = alpha_positive
    earlier_period_outperforms = earlier_alpha > 0
    recent_period_outperforms = recent_alpha_positive
    enough_trades = trade_count >= min_trade_count
    not_too_many_trades = trade_count <= max_trade_count
    max_drawdown_acceptable = max_drawdown >= max_drawdown_limit_pct
    if drawdown_delta is None:
        drawdown_improvement_vs_benchmark = None
        drawdown_not_much_worse_than_benchmark = max_drawdown_acceptable
        drawdown_much_better_than_benchmark = False
    else:
        drawdown_delta_float = float(drawdown_delta)
        drawdown_improvement_vs_benchmark = drawdown_delta_float > 0
        drawdown_not_much_worse_than_benchmark = (
            drawdown_delta_float >= MAX_DRAWDOWN_WORSE_THAN_BENCHMARK_PCT
        )
        drawdown_much_better_than_benchmark = (
            drawdown_delta_float >= DRAWDOWN_WATCHLIST_IMPROVEMENT_PCT
        )

    trade_count_reasonable = enough_trades and not_too_many_trades
    split_period_outperforms_count = int(earlier_period_outperforms) + int(
        recent_period_outperforms
    )
    recent_alpha_not_severely_negative = recent_alpha >= RECENT_ALPHA_GALLERY_FLOOR_PCT
    gallery_ready_outperformance = (
        alpha_positive
        and recent_alpha_not_severely_negative
        and drawdown_not_much_worse_than_benchmark
        and trade_count_reasonable
    )
    gallery_ready_defensive = (
        not gallery_ready_outperformance
        and drawdown_delta is not None
        and float(drawdown_delta) >= DEFENSIVE_DRAWDOWN_IMPROVEMENT_PCT
        and recent_alpha >= RECENT_ALPHA_WATCHLIST_FLOOR_PCT
        and trade_count_reasonable
    )
    gallery_ready = gallery_ready_outperformance or gallery_ready_defensive
    watchlist = (
        not gallery_ready
        and enough_trades
        and not_too_many_trades
        and recent_alpha >= RECENT_ALPHA_WATCHLIST_FLOOR_PCT
        and (
            full_alpha >= ALPHA_WATCHLIST_FLOOR_PCT
            or drawdown_much_better_than_benchmark
            or (sharpe >= 0.75 and cagr > 0)
        )
    )
    basic_sanity_pass = gallery_ready

    return {
        "gallery_ready_outperformance": gallery_ready_outperformance,
        "gallery_ready_defensive": gallery_ready_defensive,
        "gallery_ready": gallery_ready,
        "watchlist": watchlist,
        "full_period_outperforms": full_period_outperforms,
        "earlier_period_outperforms": earlier_period_outperforms,
        "recent_period_outperforms": recent_period_outperforms,
        "split_period_outperforms_count": split_period_outperforms_count,
        "drawdown_improvement_vs_benchmark": drawdown_improvement_vs_benchmark,
        "enough_trades": enough_trades,
        "not_too_many_trades": not_too_many_trades,
        "alpha_positive": alpha_positive,
        "recent_alpha_positive": recent_alpha_positive,
        "max_drawdown_acceptable": max_drawdown_acceptable,
        "trade_count_reasonable": trade_count_reasonable,
        "basic_sanity_pass": basic_sanity_pass,
        "benchmark_comparison_basis": benchmark_comparison_basis,
        "primary_alpha_pct": full_alpha,
        "train_primary_alpha_pct": earlier_alpha,
        "holdout_primary_alpha_pct": recent_alpha,
        "primary_drawdown_delta_pct": drawdown_delta,
    }


def _score_row(row: dict[str, Any]) -> float:
    full_alpha = float(
        row.get(
            "primary_alpha_pct",
            row.get("alpha_vs_tradable_buy_hold_pct", row.get("alpha_vs_benchmark_pct", 0)),
        )
        or 0
    )
    earlier_alpha = float(
        row.get(
            "train_primary_alpha_pct",
            row.get("train_alpha_vs_tradable_buy_hold_pct", row.get("earlier_alpha_vs_benchmark_pct", 0)),
        )
        or 0
    )
    recent_alpha = float(
        row.get(
            "holdout_primary_alpha_pct",
            row.get("holdout_alpha_vs_tradable_buy_hold_pct", row.get("recent_alpha_vs_benchmark_pct", 0)),
        )
        or 0
    )
    cagr = float(row.get("cagr_pct", 0) or 0)
    sharpe = float(row.get("sharpe_ratio", 0) or 0)
    max_drawdown = float(row.get("max_drawdown_pct", 0) or 0)

    score = (
        full_alpha
        + (0.35 * earlier_alpha)
        + (0.75 * recent_alpha)
        + (0.10 * cagr)
        + (2.0 * sharpe)
        + (0.08 * max_drawdown)
    )
    if not row.get("full_period_outperforms"):
        score -= 25
    if not row.get("recent_period_outperforms"):
        score -= 50
    if not row.get("trade_count_reasonable"):
        score -= 10
    if not row.get("max_drawdown_acceptable"):
        score -= 10
    if row.get("gallery_ready_outperformance"):
        score += 25
    elif row.get("gallery_ready_defensive"):
        score += 18
    elif row.get("watchlist"):
        score += 10
    return round(score, 6)


def rank_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored_rows = []
    for row in rows:
        next_row = dict(row)
        next_row["score"] = _score_row(next_row)
        scored_rows.append(next_row)

    return sorted(
        scored_rows,
        key=lambda row: (
            bool(row.get("gallery_ready_outperformance")),
            bool(row.get("gallery_ready_defensive")),
            bool(row.get("watchlist")),
            bool(row.get("gallery_ready")),
            bool(row.get("basic_sanity_pass")),
            bool(row.get("full_period_outperforms")),
            bool(row.get("recent_period_outperforms")),
            int(row.get("split_period_outperforms_count", 0) or 0),
            float(row.get("score", 0) or 0),
            float(row.get("primary_alpha_pct", 0) or 0),
            float(row.get("alpha_vs_benchmark_pct", 0) or 0),
            float(row.get("max_drawdown_pct", 0) or 0),
        ),
        reverse=True,
    )


def _row_from_periods(
    *,
    candidate: CandidateConfig,
    full_period: dict[str, Any],
    earlier_period: dict[str, Any],
    recent_period: dict[str, Any],
) -> dict[str, Any]:
    flags = build_candidate_flags(
        full_period=full_period,
        earlier_period=earlier_period,
        recent_period=recent_period,
    )
    row = {
        "candidate_id": candidate.candidate_id,
        "strategy_family": candidate.family,
        "symbol": candidate.config["tradable_symbol"],
        "benchmark": candidate.config["benchmark_symbol"],
        "strategy_name": candidate.config["name"],
        "config_summary": candidate.config_summary,
        "config_hash": candidate.config_hash or _hash_config(candidate.config, include_name=False),
        "start_date": full_period.get("start_date"),
        "end_date": full_period.get("end_date"),
        "strategy_return_pct": full_period.get("strategy_return_pct", full_period.get("total_return_pct")),
        "total_return_pct": full_period.get("total_return_pct"),
        "tradable_buy_hold_return_pct": full_period.get("tradable_buy_hold_return_pct"),
        "alpha_vs_tradable_buy_hold_pct": full_period.get("alpha_vs_tradable_buy_hold_pct"),
        "tradable_buy_hold_max_drawdown_pct": full_period.get("tradable_buy_hold_max_drawdown_pct"),
        "drawdown_delta_vs_tradable_buy_hold_pct": full_period.get(
            "drawdown_delta_vs_tradable_buy_hold_pct"
        ),
        "market_benchmark_symbol": full_period.get("market_benchmark_symbol"),
        "market_benchmark_return_pct": full_period.get("market_benchmark_return_pct"),
        "alpha_vs_market_benchmark_pct": full_period.get("alpha_vs_market_benchmark_pct"),
        "market_benchmark_max_drawdown_pct": full_period.get("market_benchmark_max_drawdown_pct"),
        "drawdown_delta_vs_market_benchmark_pct": full_period.get(
            "drawdown_delta_vs_market_benchmark_pct"
        ),
        "universe_equal_weight_buy_hold_return_pct": full_period.get(
            "universe_equal_weight_buy_hold_return_pct"
        ),
        "alpha_vs_universe_equal_weight_pct": full_period.get(
            "alpha_vs_universe_equal_weight_pct"
        ),
        "universe_equal_weight_buy_hold_max_drawdown_pct": full_period.get(
            "universe_equal_weight_buy_hold_max_drawdown_pct"
        ),
        "drawdown_delta_vs_universe_equal_weight_pct": full_period.get(
            "drawdown_delta_vs_universe_equal_weight_pct"
        ),
        "rebalance_count": full_period.get("rebalance_count"),
        "benchmark_return_pct": full_period.get("benchmark_return_pct"),
        "alpha_vs_benchmark_pct": full_period.get("alpha_vs_benchmark_pct"),
        "cagr_pct": full_period.get("cagr_pct"),
        "max_drawdown_pct": full_period.get("max_drawdown_pct"),
        "benchmark_max_drawdown_pct": full_period.get("benchmark_max_drawdown_pct"),
        "drawdown_delta_vs_benchmark_pct": full_period.get("drawdown_delta_vs_benchmark_pct"),
        "trade_count": full_period.get("trade_count"),
        "sharpe_ratio": full_period.get("sharpe_ratio"),
        "earlier_start_date": earlier_period.get("start_date"),
        "earlier_end_date": earlier_period.get("end_date"),
        "earlier_total_return_pct": earlier_period.get("total_return_pct"),
        "earlier_benchmark_return_pct": earlier_period.get("benchmark_return_pct"),
        "earlier_alpha_vs_benchmark_pct": earlier_period.get("alpha_vs_benchmark_pct"),
        "train_alpha_vs_tradable_buy_hold_pct": earlier_period.get(
            "alpha_vs_tradable_buy_hold_pct"
        ),
        "train_alpha_vs_universe_equal_weight_pct": earlier_period.get(
            "alpha_vs_universe_equal_weight_pct"
        ),
        "train_alpha_vs_market_benchmark_pct": earlier_period.get(
            "alpha_vs_market_benchmark_pct"
        ),
        "train_pass": flags["earlier_period_outperforms"],
        "earlier_trade_count": earlier_period.get("trade_count"),
        "earlier_rebalance_count": earlier_period.get("rebalance_count"),
        "recent_start_date": recent_period.get("start_date"),
        "recent_end_date": recent_period.get("end_date"),
        "recent_total_return_pct": recent_period.get("total_return_pct"),
        "recent_benchmark_return_pct": recent_period.get("benchmark_return_pct"),
        "recent_alpha_vs_benchmark_pct": recent_period.get("alpha_vs_benchmark_pct"),
        "holdout_alpha_vs_tradable_buy_hold_pct": recent_period.get(
            "alpha_vs_tradable_buy_hold_pct"
        ),
        "holdout_alpha_vs_universe_equal_weight_pct": recent_period.get(
            "alpha_vs_universe_equal_weight_pct"
        ),
        "holdout_alpha_vs_market_benchmark_pct": recent_period.get(
            "alpha_vs_market_benchmark_pct"
        ),
        "holdout_pass": flags["holdout_primary_alpha_pct"] >= RECENT_ALPHA_GALLERY_FLOOR_PCT,
        "recent_trade_count": recent_period.get("trade_count"),
        "recent_rebalance_count": recent_period.get("rebalance_count"),
        **flags,
    }
    row["stability_flag"] = (
        "train_and_holdout_pass"
        if row["train_pass"] and row["holdout_pass"]
        else "holdout_only"
        if row["holdout_pass"]
        else "train_only"
        if row["train_pass"]
        else "unstable"
    )
    row["candidate_category"] = (
        "gallery_ready_outperformance"
        if row.get("gallery_ready_outperformance")
        else "gallery_ready_defensive"
        if row.get("gallery_ready_defensive")
        else "watchlist"
        if row.get("watchlist")
        else "failed"
    )
    return row


def build_evaluation_metadata(
    *,
    mode: SearchMode,
    start_date: str,
    end_date: str,
    periods: list[PeriodSpec],
) -> dict[str, Any]:
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "mode": mode,
        "start_date": start_date,
        "end_date": end_date,
        "periods": [period.__dict__ for period in periods],
        "split_policy": "full_65pct_train_recent_holdout",
        "benchmark_policy": (
            "tradable_buy_hold_and_market_benchmark; "
            "rotation_candidates_also_use_universe_equal_weight_buy_hold"
        ),
    }


def build_candidate_cache_key(
    candidate: CandidateConfig,
    *,
    periods: list[PeriodSpec],
    evaluation_metadata: dict[str, Any] | None = None,
) -> str:
    metadata = evaluation_metadata or {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "periods": [period.__dict__ for period in periods],
    }
    payload = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "canonical_config": _canonical_config(candidate.config),
        "evaluation_metadata": metadata,
    }
    return _sha256_json(payload)


def _cache_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / f"{cache_key}.json"


def _read_cached_candidate(cache_dir: Path, cache_key: str) -> dict[str, Any] | None:
    path = _cache_path(cache_dir, cache_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Warning: ignoring corrupt discovery cache {path}: {exc}")
        return None
    if not isinstance(payload, dict):
        print(f"Warning: ignoring invalid discovery cache {path}: expected object")
        return None
    if payload.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        print(f"Warning: ignoring incompatible discovery cache {path}: schema mismatch")
        return None
    if payload.get("cache_key") != cache_key:
        print(f"Warning: ignoring incompatible discovery cache {path}: key mismatch")
        return None
    status = payload.get("status")
    if status == "success" and isinstance(payload.get("row"), dict):
        return payload
    if status == "failed" and isinstance(payload.get("error"), str):
        return payload
    print(f"Warning: ignoring invalid discovery cache {path}: missing cached result")
    return None


def _write_candidate_cache(
    *,
    cache_dir: Path,
    cache_key: str,
    candidate: CandidateConfig,
    status: Literal["success", "failed"],
    evaluation_metadata: dict[str, Any],
    row: dict[str, Any] | None = None,
    error: str | None = None,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "cache_key": cache_key,
        "candidate_id": candidate.candidate_id,
        "config_hash": candidate.config_hash or _hash_config(candidate.config, include_name=False),
        "config": candidate.config,
        "status": status,
        "row": row,
        "error": error,
        "evaluation_metadata": evaluation_metadata,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _cache_path(cache_dir, cache_key)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _execute_candidate_evaluation(
    candidate: CandidateConfig,
    periods: list[PeriodSpec],
    loader: _MarketDataLoader,
) -> dict[str, Any]:
    period_metrics = {
        period.label: _evaluate_period(
            candidate=candidate,
            period=period,
            loader=loader,
        )
        for period in periods
    }
    return _row_from_periods(
        candidate=candidate,
        full_period=period_metrics["full"],
        earlier_period=period_metrics["earlier"],
        recent_period=period_metrics["recent_holdout"],
    )


def evaluate_candidates_with_cache(
    *,
    candidates: list[CandidateConfig],
    periods: list[PeriodSpec],
    loader: _MarketDataLoader | None,
    resume: bool,
    cache_dir: Path,
    evaluation_metadata: dict[str, Any],
    evaluator: Callable[[CandidateConfig, list[PeriodSpec], _MarketDataLoader | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    cache_hits = 0
    executed = 0

    run_evaluator = evaluator or _execute_candidate_evaluation

    for index, candidate in enumerate(candidates, start=1):
        cache_key = build_candidate_cache_key(
            candidate,
            periods=periods,
            evaluation_metadata=evaluation_metadata,
        )
        prefix = f"[{index}/{len(candidates)}] {candidate.candidate_id}"

        if resume:
            cached = _read_cached_candidate(cache_dir, cache_key)
            if cached is not None:
                cache_hits += 1
                if cached["status"] == "success":
                    rows.append(cached["row"])
                    print(f"{prefix} cached/skipped success")
                else:
                    failed_rows.append(
                        {
                            "candidate_id": cached.get("candidate_id", candidate.candidate_id),
                            "strategy_family": candidate.family,
                            "strategy_name": candidate.config["name"],
                            "cache_key": cache_key,
                            "error": cached.get("error", "cached failure"),
                        }
                    )
                    print(f"{prefix} cached/skipped failed")
                continue

        print(f"{prefix} executing")
        executed += 1
        try:
            row = run_evaluator(candidate, periods, loader)
            row["cache_key"] = cache_key
            rows.append(row)
            if resume:
                _write_candidate_cache(
                    cache_dir=cache_dir,
                    cache_key=cache_key,
                    candidate=candidate,
                    status="success",
                    evaluation_metadata=evaluation_metadata,
                    row=row,
                )
            print(f"{prefix} executed success")
        except Exception as exc:  # pragma: no cover - exercised by real data edge cases
            error = str(exc)
            failed_row = {
                "candidate_id": candidate.candidate_id,
                "strategy_family": candidate.family,
                "strategy_name": candidate.config["name"],
                "cache_key": cache_key,
                "error": error,
            }
            failed_rows.append(failed_row)
            if resume:
                _write_candidate_cache(
                    cache_dir=cache_dir,
                    cache_key=cache_key,
                    candidate=candidate,
                    status="failed",
                    evaluation_metadata=evaluation_metadata,
                    error=error,
                )
            print(f"{prefix} failed: {error}")

    return {
        "rows": rows,
        "failed_rows": failed_rows,
        "cache_hits": cache_hits,
        "executed": executed,
        "selected_count": len(candidates),
    }


def _csv_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "config"}


def split_candidate_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    gallery_ready_outperformance = [
        row for row in rows if row.get("gallery_ready_outperformance")
    ]
    gallery_ready_defensive = [
        row for row in rows if row.get("gallery_ready_defensive")
    ]
    watchlist = [row for row in rows if row.get("watchlist")]
    failed = [
        row
        for row in rows
        if not row.get("gallery_ready_outperformance")
        and not row.get("gallery_ready_defensive")
        and not row.get("watchlist")
    ]
    return {
        "gallery_ready_outperformance": gallery_ready_outperformance,
        "gallery_ready_defensive": gallery_ready_defensive,
        "gallery_ready": gallery_ready_outperformance + gallery_ready_defensive,
        "watchlist": watchlist,
        "failed": failed,
    }


def build_report_counts(
    *,
    candidate_count: int,
    ranked_rows: list[dict[str, Any]],
    failed_rows: list[dict[str, Any]],
    total_generated: int | None = None,
    cache_hits: int = 0,
    executed: int = 0,
    market_data_cache_stats: dict[str, int] | None = None,
) -> dict[str, int]:
    splits = split_candidate_rows(ranked_rows)
    cache_stats = market_data_cache_stats or {}
    return {
        "total_generated": total_generated if total_generated is not None else candidate_count,
        "total_candidates": candidate_count,
        "selected_for_run": candidate_count,
        "successful": len(ranked_rows),
        "failed": len(failed_rows),
        "cache_hits": cache_hits,
        "executed": executed,
        "bundle_cache_hits": int(cache_stats.get("bundle_cache_hits", 0)),
        "bundle_cache_misses": int(cache_stats.get("bundle_cache_misses", 0)),
        "symbol_frame_cache_hits": int(cache_stats.get("symbol_frame_cache_hits", 0)),
        "symbol_frame_cache_misses": int(cache_stats.get("symbol_frame_cache_misses", 0)),
        "gallery_ready_count": len(splits["gallery_ready"]),
        "gallery_ready_outperformance_count": len(splits["gallery_ready_outperformance"]),
        "gallery_ready_defensive_count": len(splits["gallery_ready_defensive"]),
        "watchlist_count": len(splits["watchlist"]),
        "sanity_failed_count": len(splits["failed"]),
    }


def _rows_with_configs(
    rows: list[dict[str, Any]],
    config_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [{**row, "config": config_by_id[row["candidate_id"]]} for row in rows]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_csv_safe_row(row) for row in rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_split_artifacts(
    *,
    run_dir: Path,
    name: str,
    rows: list[dict[str, Any]],
    config_by_id: dict[str, dict[str, Any]],
    fieldnames: list[str],
) -> dict[str, Path]:
    csv_path = run_dir / f"{name}.csv"
    json_path = run_dir / f"{name}.json"
    _write_csv(csv_path, rows, fieldnames)
    _write_json(json_path, _rows_with_configs(rows, config_by_id))
    return {f"{name}_csv": csv_path, f"{name}_json": json_path}


def _write_outputs(
    *,
    run_dir: Path,
    ranked_rows: list[dict[str, Any]],
    failed_rows: list[dict[str, Any]],
    candidates: list[CandidateConfig],
    periods: list[PeriodSpec],
    top_n: int,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_path = run_dir / "candidate_summary.csv"
    fieldnames = list(_csv_safe_row(ranked_rows[0]).keys()) if ranked_rows else []
    if ranked_rows:
        _write_csv(csv_path, ranked_rows, fieldnames)
    else:
        _write_csv(
            csv_path,
            [],
            [
                "candidate_id",
                "strategy_family",
                "symbol",
                "benchmark",
                "alpha_vs_benchmark_pct",
                "gallery_ready",
                "watchlist",
            ],
        )
        fieldnames = [
            "candidate_id",
            "strategy_family",
            "symbol",
            "benchmark",
            "alpha_vs_benchmark_pct",
            "gallery_ready",
            "watchlist",
        ]

    config_by_id = {candidate.candidate_id: candidate.config for candidate in candidates}
    json_rows = _rows_with_configs(ranked_rows, config_by_id)
    splits = split_candidate_rows(ranked_rows)
    report_counts = build_report_counts(
        candidate_count=len(candidates),
        ranked_rows=ranked_rows,
        failed_rows=failed_rows,
        total_generated=(run_metadata or {}).get("total_generated"),
        cache_hits=(run_metadata or {}).get("cache_hits", 0),
        executed=(run_metadata or {}).get("executed", 0),
        market_data_cache_stats=(run_metadata or {}).get("market_data_cache_stats"),
    )

    json_path = run_dir / "candidate_summary.json"
    _write_json(
        json_path,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "periods": [period.__dict__ for period in periods],
            "run_metadata": run_metadata or {},
            **report_counts,
            "results": json_rows,
            "gallery_ready_outperformance": _rows_with_configs(
                splits["gallery_ready_outperformance"],
                config_by_id,
            ),
            "gallery_ready_defensive": _rows_with_configs(
                splits["gallery_ready_defensive"],
                config_by_id,
            ),
            "gallery_ready_candidates": _rows_with_configs(splits["gallery_ready"], config_by_id),
            "watchlist_candidates": _rows_with_configs(splits["watchlist"], config_by_id),
            "sanity_failed_candidates": _rows_with_configs(splits["failed"], config_by_id),
            "failures": failed_rows,
            "disclaimer": (
                "Historical backtests are research screens only. "
                "They are not performance promises or robustness proof."
            ),
        },
    )

    paths = {"csv": csv_path, "json": json_path}
    paths.update(
        _write_split_artifacts(
            run_dir=run_dir,
            name="gallery_ready_outperformance",
            rows=splits["gallery_ready_outperformance"],
            config_by_id=config_by_id,
            fieldnames=fieldnames,
        )
    )
    paths.update(
        _write_split_artifacts(
            run_dir=run_dir,
            name="gallery_ready_defensive",
            rows=splits["gallery_ready_defensive"],
            config_by_id=config_by_id,
            fieldnames=fieldnames,
        )
    )
    paths.update(
        _write_split_artifacts(
            run_dir=run_dir,
            name="watchlist_candidates",
            rows=splits["watchlist"],
            config_by_id=config_by_id,
            fieldnames=fieldnames,
        )
    )
    paths.update(
        _write_split_artifacts(
            run_dir=run_dir,
            name="failed_candidates",
            rows=splits["failed"],
            config_by_id=config_by_id,
            fieldnames=fieldnames,
        )
    )

    top_by_alpha = sorted(
        ranked_rows,
        key=lambda row: float(row.get("alpha_vs_tradable_buy_hold_pct", 0) or 0),
        reverse=True,
    )[:top_n]
    top_by_alpha_path = run_dir / "top_by_alpha_vs_tradable.csv"
    _write_csv(top_by_alpha_path, top_by_alpha, fieldnames)
    paths["top_by_alpha_vs_tradable_csv"] = top_by_alpha_path

    rows_with_drawdown = [
        row for row in ranked_rows if row.get("drawdown_delta_vs_tradable_buy_hold_pct") is not None
    ]
    top_by_drawdown_path = run_dir / "top_by_drawdown_improvement.csv"
    top_by_drawdown = sorted(
        rows_with_drawdown,
        key=lambda row: float(row.get("drawdown_delta_vs_tradable_buy_hold_pct", 0) or 0),
        reverse=True,
    )[:top_n]
    _write_csv(top_by_drawdown_path, top_by_drawdown, fieldnames)
    paths["top_by_drawdown_improvement_csv"] = top_by_drawdown_path

    top_by_recent_alpha_path = run_dir / "top_by_recent_alpha.csv"
    top_by_recent_alpha = sorted(
        ranked_rows,
        key=lambda row: float(row.get("holdout_primary_alpha_pct", row.get("holdout_alpha_vs_tradable_buy_hold_pct", 0)) or 0),
        reverse=True,
    )[:top_n]
    _write_csv(top_by_recent_alpha_path, top_by_recent_alpha, fieldnames)
    paths["top_by_recent_alpha_csv"] = top_by_recent_alpha_path

    top_by_primary_alpha_path = run_dir / "top_by_primary_alpha.csv"
    top_by_primary_alpha = sorted(
        ranked_rows,
        key=lambda row: float(row.get("primary_alpha_pct", row.get("alpha_vs_tradable_buy_hold_pct", 0)) or 0),
        reverse=True,
    )[:top_n]
    _write_csv(top_by_primary_alpha_path, top_by_primary_alpha, fieldnames)
    paths["top_by_primary_alpha_csv"] = top_by_primary_alpha_path

    top_dir = run_dir / "candidate_configs"
    top_dir.mkdir(parents=True, exist_ok=True)
    for stale_file in top_dir.glob("top_*.json"):
        stale_file.unlink()
    export_rows = (splits["gallery_ready"] + splits["watchlist"])[:top_n]
    for index, row in enumerate(export_rows, start=1):
        config = config_by_id[row["candidate_id"]]
        path = top_dir / f"top_{index:03d}_{row['candidate_id']}.json"
        path.write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")
    paths["top_configs"] = top_dir

    return paths


def run_discovery(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    mode: SearchMode = "standard",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_id: str = "latest",
    max_candidates: int | None = None,
    families: set[str] | None = None,
    top_n: int = TOP_CONFIG_COUNT,
    data_path: str | None = None,
    refine_input: Path | None = None,
    resume: bool = False,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    settings = get_settings()
    resolved_start = start_date or settings.supported_data_start.isoformat()
    resolved_end = end_date or settings.supported_data_end.isoformat()

    candidates = generate_candidate_configs(
        start_date=resolved_start,
        end_date=resolved_end,
        mode=mode,
        refine_input=refine_input,
        supported_etfs=settings.supported_etf_symbols,
        supported_reference_series=settings.supported_reference_series_symbols,
    )
    total_generated = len(candidates)
    available_families = sorted({candidate.family for candidate in candidates})
    requested_families: list[str] | None = None
    unmatched_families: list[str] = []
    if families:
        normalized_families = {family.strip() for family in families if family.strip()}
        requested_families = sorted(normalized_families)
        unmatched_families = sorted(normalized_families - set(available_families))
        candidates = [
            candidate
            for candidate in candidates
            if candidate.family in normalized_families
        ]
    total_after_family_filter = len(candidates)
    candidates = select_candidates_for_run(candidates, max_candidates=max_candidates)

    periods = build_split_periods(resolved_start, resolved_end)
    repo = MarketDataRepository(
        market_data_path=data_path or settings.market_data_path,
        reference_series_data_path=settings.reference_series_data_path,
        supported_reference_series_symbols=settings.supported_reference_series_symbols,
        duckdb_database=settings.duckdb_database,
        s3_region=settings.s3_region,
    )
    loader = _MarketDataLoader(repo)

    evaluation_metadata = build_evaluation_metadata(
        mode=mode,
        start_date=resolved_start,
        end_date=resolved_end,
        periods=periods,
    )
    evaluation_result = evaluate_candidates_with_cache(
        candidates=candidates,
        periods=periods,
        loader=loader,
        resume=resume,
        cache_dir=cache_dir,
        evaluation_metadata=evaluation_metadata,
    )
    market_data_cache_stats = loader.cache_stats()
    rows = evaluation_result["rows"]
    failed_rows = evaluation_result["failed_rows"]

    ranked_rows = rank_candidate_rows(rows)
    splits = split_candidate_rows(ranked_rows)
    report_counts = build_report_counts(
        candidate_count=len(candidates),
        ranked_rows=ranked_rows,
        failed_rows=failed_rows,
        total_generated=total_generated,
        cache_hits=evaluation_result["cache_hits"],
        executed=evaluation_result["executed"],
        market_data_cache_stats=market_data_cache_stats,
    )
    run_dir = output_dir / run_id
    run_metadata = {
        "mode": mode,
        "resume": resume,
        "cache_dir": str(cache_dir),
        "total_generated": total_generated,
        "total_after_family_filter": total_after_family_filter,
        "selected_for_run": len(candidates),
        "max_candidates": max_candidates,
        "families": requested_families,
        "available_families": available_families,
        "unmatched_families": unmatched_families,
        "cache_hits": evaluation_result["cache_hits"],
        "executed": evaluation_result["executed"],
        "market_data_cache_stats": market_data_cache_stats,
        "evaluation_metadata": evaluation_metadata,
    }
    paths = _write_outputs(
        run_dir=run_dir,
        ranked_rows=ranked_rows,
        failed_rows=failed_rows,
        candidates=candidates,
        periods=periods,
        top_n=top_n,
        run_metadata=run_metadata,
    )

    return {
        "run_dir": run_dir,
        "paths": paths,
        "ranked_rows": ranked_rows,
        "gallery_ready_rows": splits["gallery_ready"],
        "watchlist_rows": splits["watchlist"],
        "sanity_failed_rows": splits["failed"],
        "failed_rows": failed_rows,
        "report_counts": report_counts,
        "run_metadata": run_metadata,
        "candidate_count": len(candidates),
        "total_generated": total_generated,
        "available_families": available_families,
        "unmatched_families": unmatched_families,
        "cache_hits": evaluation_result["cache_hits"],
        "executed": evaluation_result["executed"],
        "market_data_cache_stats": market_data_cache_stats,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover historically interesting Strategy V2 Gallery candidates."
    )
    parser.add_argument("--start-date", help="Backtest start date. Defaults to SUPPORTED_DATA_START_DATE.")
    parser.add_argument("--end-date", help="Backtest end date. Defaults to SUPPORTED_DATA_END_DATE.")
    parser.add_argument("--data-path", help="Override MARKET_DATA_PATH for ETF bars.")
    parser.add_argument(
        "--mode",
        choices=["smoke", "standard", "broad", "refine"],
        default="standard",
        help="Search breadth. broad is intended for longer local research runs.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for ignored discovery reports.",
    )
    parser.add_argument(
        "--run-id",
        default="latest",
        help="Subdirectory name under output-dir. Defaults to latest.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        help="Optional deterministic cap for smoke runs.",
    )
    parser.add_argument(
        "--families",
        help="Comma-separated candidate families to run, e.g. trend_pullback,core_rsi_overlay.",
    )
    parser.add_argument(
        "--refine-input",
        help="Optional JSON summary/config file for --mode refine.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse cached candidate evaluations and skip already completed candidates.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Directory for local per-candidate discovery cache files.",
    )
    parser.add_argument("--top-n", type=int, default=TOP_CONFIG_COUNT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = run_discovery(
        start_date=args.start_date,
        end_date=args.end_date,
        mode=args.mode,
        data_path=args.data_path,
        output_dir=Path(args.output_dir),
        run_id=args.run_id,
        max_candidates=args.max_candidates,
        families=set(args.families.split(",")) if args.families else None,
        top_n=args.top_n,
        refine_input=Path(args.refine_input) if args.refine_input else None,
        resume=args.resume,
        cache_dir=Path(args.cache_dir),
    )

    counts = result["report_counts"]
    print("\n=== Discovery Complete ===")
    print(f"Mode: {args.mode}")
    print(f"Total generated: {counts['total_generated']}")
    print(f"Available families: {', '.join(result['available_families'])}")
    if result["unmatched_families"]:
        print(f"Unmatched family filters: {', '.join(result['unmatched_families'])}")
        print("Use one or more available family names with --families.")
    print(f"Selected for this run: {counts['selected_for_run']}")
    print(f"Cache hits / skipped: {counts['cache_hits']}")
    print(f"Executed: {counts['executed']}")
    print(f"Bundle cache hits: {counts['bundle_cache_hits']}")
    print(f"Bundle cache misses: {counts['bundle_cache_misses']}")
    print(f"Symbol-frame cache hits: {counts['symbol_frame_cache_hits']}")
    print(f"Symbol-frame cache misses: {counts['symbol_frame_cache_misses']}")
    print(f"Successful: {counts['successful']}")
    print(f"Failed: {counts['failed']}")
    print(f"Gallery-ready outperformance: {counts['gallery_ready_outperformance_count']}")
    print(f"Gallery-ready defensive: {counts['gallery_ready_defensive_count']}")
    print(f"Gallery-ready total: {counts['gallery_ready_count']}")
    print(f"Watchlist: {counts['watchlist_count']}")
    print(f"Sanity failed: {counts['sanity_failed_count']}")
    print(f"CSV: {result['paths']['csv']}")
    print(f"JSON: {result['paths']['json']}")

    display_columns = [
        "candidate_id",
        "strategy_family",
        "candidate_category",
        "symbol",
        "benchmark",
        "benchmark_comparison_basis",
        "primary_alpha_pct",
        "holdout_primary_alpha_pct",
        "alpha_vs_tradable_buy_hold_pct",
        "holdout_alpha_vs_tradable_buy_hold_pct",
        "alpha_vs_universe_equal_weight_pct",
        "holdout_alpha_vs_universe_equal_weight_pct",
        "alpha_vs_market_benchmark_pct",
        "max_drawdown_pct",
        "tradable_buy_hold_max_drawdown_pct",
        "drawdown_delta_vs_tradable_buy_hold_pct",
        "universe_equal_weight_buy_hold_max_drawdown_pct",
        "drawdown_delta_vs_universe_equal_weight_pct",
        "trade_count",
        "rebalance_count",
        "score",
        "gallery_ready_outperformance",
        "gallery_ready_defensive",
        "watchlist",
    ]

    outperformance_rows = [
        row for row in result["gallery_ready_rows"] if row.get("gallery_ready_outperformance")
    ][:10]
    defensive_rows = [
        row for row in result["gallery_ready_rows"] if row.get("gallery_ready_defensive")
    ][:10]
    if outperformance_rows:
        print("\n=== Gallery-Ready Outperformance Candidates ===")
        print(pd.DataFrame(outperformance_rows)[display_columns].to_string(index=False))
    if defensive_rows:
        print("\n=== Gallery-Ready Defensive Candidates ===")
        print(pd.DataFrame(defensive_rows)[display_columns].to_string(index=False))
        print("Defensive candidates are risk-improvement candidates, not return-outperformance claims.")
    if not outperformance_rows and not defensive_rows:
        print("\nNo Gallery-ready candidates found.")
    else:
        pass

    watchlist_rows = result["watchlist_rows"][:10]
    if watchlist_rows:
        print("\n=== Watchlist Candidates ===")
        print(pd.DataFrame(watchlist_rows)[display_columns].to_string(index=False))

    failed_preview = result["sanity_failed_rows"][:10]
    if failed_preview:
        print("\n=== Least-Bad Failed Candidates ===")
        print(
            "These candidates did not meet Gallery-ready or watchlist filters; "
            "review only for diagnosis."
        )
        table = pd.DataFrame(failed_preview)[
            [
                "candidate_id",
                "strategy_family",
                "candidate_category",
                "symbol",
                "benchmark",
                "benchmark_comparison_basis",
                "primary_alpha_pct",
                "holdout_primary_alpha_pct",
                "alpha_vs_tradable_buy_hold_pct",
                "holdout_alpha_vs_tradable_buy_hold_pct",
                "alpha_vs_universe_equal_weight_pct",
                "holdout_alpha_vs_universe_equal_weight_pct",
                "max_drawdown_pct",
                "drawdown_delta_vs_tradable_buy_hold_pct",
                "drawdown_delta_vs_universe_equal_weight_pct",
                "trade_count",
                "rebalance_count",
                "score",
                "gallery_ready_outperformance",
                "gallery_ready_defensive",
                "watchlist",
            ]
        ]
        print(table.to_string(index=False))


if __name__ == "__main__":
    main()
