from __future__ import annotations

import ast
import csv
import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3

from market_simulator.platform.services.trade_event_inspector import _normalize_date
from market_simulator.settings import get_settings


MAX_REBALANCE_EVENTS = 120


class RotationReviewService:
    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self._s3 = None

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=self.settings.artifact_s3_region)
        return self._s3

    @lru_cache(maxsize=512)
    def _read_text(self, uri: str) -> str:
        if uri.startswith("s3://"):
            parsed = urlparse(uri)
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
            obj = self.s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read().decode("utf-8")

        return Path(uri).read_text(encoding="utf-8")

    def _load_csv_rows(self, uri: str) -> list[dict[str, str]]:
        text = self._read_text(uri)
        return list(csv.DictReader(io.StringIO(text)))

    def _load_json(self, uri: str | None) -> dict[str, Any]:
        if not uri:
            return {}
        try:
            payload = json.loads(self._read_text(uri))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def load_rotation_review(
        self,
        artifact_manifest_json: dict[str, str],
        *,
        config: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
        limit: int = MAX_REBALANCE_EVENTS,
    ) -> dict[str, Any] | None:
        timeline_uri = artifact_manifest_json.get("timeline")
        trade_log_uri = artifact_manifest_json.get("trade_log")
        if not timeline_uri:
            return None

        known_rotation = is_rotation_run(config=config, summary=summary)
        try:
            timeline_rows = self._load_csv_rows(timeline_uri)
        except Exception:
            if known_rotation:
                raise
            return None

        if not known_rotation and not is_rotation_run(timeline_rows=timeline_rows):
            return None

        trade_rows = self._load_csv_rows(trade_log_uri) if trade_log_uri else []
        report_bundle = self._load_json(artifact_manifest_json.get("report_bundle"))
        report_summary = report_bundle.get("summary") if isinstance(report_bundle.get("summary"), dict) else {}
        summary_source = {
            **(report_summary if isinstance(report_summary, dict) else {}),
            **(summary if isinstance(summary, dict) else {}),
        }

        universe = _rotation_universe(config=config, summary=summary_source)
        rebalances = build_rotation_rebalance_rows(
            timeline_rows,
            trade_rows,
            universe=universe,
            limit=limit,
        )

        return {
            "is_rotation": True,
            "metrics": build_rotation_summary_metrics(
                summary=summary_source,
                rebalances=rebalances,
                universe=universe,
            ),
            "total_count": len([row for row in timeline_rows if _is_rebalance_row(row)]),
            "rebalances": rebalances,
        }


def is_rotation_run(
    *,
    config: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    timeline_rows: list[dict[str, Any]] | None = None,
) -> bool:
    rotation = config.get("rotation") if isinstance(config, dict) else None
    if isinstance(rotation, dict) and rotation.get("enabled") is True:
        return True

    if isinstance(summary, dict):
        if summary.get("strategy_type") == "rotation":
            return True
        if isinstance(summary.get("rotation_universe"), list):
            return True

    if timeline_rows:
        first_row = timeline_rows[0]
        rotation_columns = {
            "rebalance",
            "selected_assets",
            "target_weights",
            "asset_returns",
            "asset_ranks",
        }
        return any(column in first_row for column in rotation_columns)

    return False


def build_rotation_rebalance_rows(
    timeline_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    *,
    universe: list[str] | None = None,
    limit: int = MAX_REBALANCE_EVENTS,
) -> list[dict[str, Any]]:
    trades_by_date: dict[str, list[dict[str, Any]]] = {}
    for trade in trade_rows:
        trade_date = _normalize_date(
            trade.get("date")
            or trade.get("Date")
            or trade.get("entry_date")
            or trade.get("exit_date")
        )
        if not trade_date:
            continue
        trades_by_date.setdefault(trade_date, []).append(_trade_row(trade))

    rebalances: list[dict[str, Any]] = []
    for row in timeline_rows:
        if not _is_rebalance_row(row):
            continue

        date_value = _normalize_date(row.get("date") or row.get("Date"))
        if not date_value:
            continue

        selected_assets = _string_list(row.get("selected_assets"))
        target_weights = _number_map(row.get("target_weights"))
        asset_returns = _number_map(row.get("asset_returns"))
        asset_ranks = _number_map(row.get("asset_ranks"))
        model_scores = _number_map(row.get("model_scores"))
        model_ranks = _number_map(row.get("model_ranks"))
        model_signal_dates = _string_map(row.get("model_signal_dates"))
        model_signal_buckets = _string_map(row.get("model_signal_buckets"))
        holdings = _holdings(row, universe=universe)

        rebalances.append(
            {
                "id": f"rotation-rebalance-{date_value}-{len(rebalances)}",
                "date": date_value,
                "selected_assets": selected_assets,
                "target_weights": target_weights,
                "asset_ranks": _asset_rank_rows(
                    selected_assets=selected_assets,
                    target_weights=target_weights,
                    asset_returns=asset_returns,
                    asset_ranks=asset_ranks,
                    model_scores=model_scores,
                    model_ranks=model_ranks,
                    model_signal_dates=model_signal_dates,
                    model_signal_buckets=model_signal_buckets,
                ),
                "trades": trades_by_date.get(date_value, []),
                "cash": _optional_float(row.get("cash")),
                "holdings": holdings,
                "risk_filter_passed": _optional_bool(row.get("risk_filter_passed")),
                "fallback_used": _optional_string(row.get("fallback_used")),
            }
        )

        if len(rebalances) >= limit:
            break

    return rebalances


def build_rotation_summary_metrics(
    *,
    summary: dict[str, Any],
    rebalances: list[dict[str, Any]],
    universe: list[str] | None,
) -> dict[str, Any]:
    latest_holdings = rebalances[-1]["holdings"] if rebalances else []
    summary_rebalance_count = _optional_int(summary.get("rebalance_count"))
    return {
        "strategy_return_pct": _optional_float(summary.get("total_return_pct")),
        "market_benchmark_return_pct": _optional_float(summary.get("benchmark_return_pct")),
        "universe_equal_weight_return_pct": _first_number(
            summary,
            "universe_equal_weight_return_pct",
            "universe_equal_weight_buy_hold_return_pct",
        ),
        "alpha_vs_universe_equal_weight_pct": _optional_float(
            summary.get("alpha_vs_universe_equal_weight_pct")
        ),
        "max_drawdown_pct": _optional_float(summary.get("max_drawdown_pct")),
        "rebalance_count": summary_rebalance_count if summary_rebalance_count is not None else len(rebalances),
        "held_assets_count": len(latest_holdings) if rebalances else None,
        "universe_size": len(universe) if universe else _optional_int(summary.get("rotation_universe_size")),
    }


def _is_rebalance_row(row: dict[str, Any]) -> bool:
    rebalance = _optional_bool(row.get("rebalance"))
    if rebalance is not None:
        return rebalance
    return str(row.get("action_taken") or "").strip().lower() == "rebalance"


def _rotation_universe(
    *,
    config: dict[str, Any] | None,
    summary: dict[str, Any] | None,
) -> list[str] | None:
    rotation = config.get("rotation") if isinstance(config, dict) else None
    if isinstance(rotation, dict):
        universe = _string_list(rotation.get("universe"))
        if universe:
            return universe

    if isinstance(summary, dict):
        universe = _string_list(summary.get("rotation_universe"))
        if universe:
            return universe

    return None


def _parse_collection(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def _string_list(value: Any) -> list[str]:
    parsed = _parse_collection(value)
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _number_map(value: Any) -> dict[str, float]:
    parsed = _parse_collection(value)
    if not isinstance(parsed, dict):
        return {}

    out: dict[str, float] = {}
    for key, raw_value in parsed.items():
        number = _optional_float(raw_value)
        if number is not None:
            out[str(key)] = number
    return out


def _string_map(value: Any) -> dict[str, str]:
    parsed = _parse_collection(value)
    if not isinstance(parsed, dict):
        return {}

    out: dict[str, str] = {}
    for key, raw_value in parsed.items():
        text = _optional_string(raw_value)
        if text is not None:
            out[str(key)] = text
    return out


def _holdings(row: dict[str, Any], *, universe: list[str] | None = None) -> list[dict[str, Any]]:
    parsed = _parse_collection(row.get("holdings"))
    if isinstance(parsed, dict) and parsed:
        holdings = []
        for symbol, raw_holding in sorted(parsed.items()):
            holding = raw_holding if isinstance(raw_holding, dict) else {}
            shares = _optional_float(holding.get("shares"))
            market_value = _optional_float(holding.get("market_value"))
            weight_pct = _optional_float(holding.get("weight_pct"))
            if shares is None and market_value is None and weight_pct is None:
                continue
            holdings.append(
                {
                    "symbol": str(symbol),
                    "shares": shares,
                    "market_value": market_value,
                    "weight_pct": weight_pct,
                }
            )
        return holdings

    symbols = universe or _symbols_from_holding_columns(row)
    holdings = []
    for symbol in symbols:
        shares = _optional_float(row.get(f"holding_{symbol}_shares"))
        market_value = _optional_float(row.get(f"holding_{symbol}_value"))
        weight_pct = _optional_float(row.get(f"weight_{symbol}_pct"))
        if (shares is None or shares == 0) and (market_value is None or market_value == 0):
            continue
        holdings.append(
            {
                "symbol": symbol,
                "shares": shares,
                "market_value": market_value,
                "weight_pct": weight_pct,
            }
        )
    return holdings


def _symbols_from_holding_columns(row: dict[str, Any]) -> list[str]:
    symbols = []
    for key in row:
        if key.startswith("holding_") and key.endswith("_shares"):
            symbols.append(key[len("holding_") : -len("_shares")])
    return sorted(symbols)


def _asset_rank_rows(
    *,
    selected_assets: list[str],
    target_weights: dict[str, float],
    asset_returns: dict[str, float],
    asset_ranks: dict[str, float],
    model_scores: dict[str, float] | None = None,
    model_ranks: dict[str, float] | None = None,
    model_signal_dates: dict[str, str] | None = None,
    model_signal_buckets: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    model_scores = model_scores or {}
    model_ranks = model_ranks or {}
    model_signal_dates = model_signal_dates or {}
    model_signal_buckets = model_signal_buckets or {}
    symbols = (
        set(selected_assets)
        | set(target_weights)
        | set(asset_returns)
        | set(asset_ranks)
        | set(model_scores)
        | set(model_ranks)
        | set(model_signal_dates)
        | set(model_signal_buckets)
    )
    rows = []
    for symbol in symbols:
        rows.append(
            {
                "symbol": symbol,
                "rank": _optional_int(asset_ranks.get(symbol)),
                "trailing_return_pct": (
                    round(asset_returns[symbol] * 100.0, 6)
                    if symbol in asset_returns
                    else None
                ),
                "model_score": _optional_float(model_scores.get(symbol)),
                "model_rank": _optional_int(model_ranks.get(symbol)),
                "model_signal_date": model_signal_dates.get(symbol),
                "model_signal_bucket": model_signal_buckets.get(symbol),
                "target_weight_pct": (
                    round(target_weights[symbol] * 100.0, 6)
                    if symbol in target_weights
                    else None
                ),
                "selected": symbol in selected_assets,
            }
        )

    return sorted(rows, key=_asset_rank_sort_key)


def _asset_rank_sort_key(item: dict[str, Any]) -> tuple[bool, int, str]:
    rank = item["rank"] if item["rank"] is not None else item["model_rank"]
    return rank is None, rank if rank is not None else 999999, item["symbol"]


def _trade_row(trade: dict[str, Any]) -> dict[str, Any]:
    price = _optional_float(
        trade.get("price")
        or trade.get("fill_price")
        or trade.get("entry_price")
        or trade.get("exit_price")
    )
    shares = _optional_float(
        trade.get("shares")
        or trade.get("quantity")
        or trade.get("position_shares")
    )
    return {
        "action": str(trade.get("action") or trade.get("side") or trade.get("signal") or "TRADE"),
        "symbol": _optional_string(trade.get("symbol")),
        "shares": shares,
        "price": price,
        "notional": round(shares * price, 6) if shares is not None and price is not None else None,
        "fee": _optional_float(trade.get("fee")),
        "gross_pnl": _optional_float(trade.get("gross_pnl")),
        "net_pnl": _optional_float(trade.get("net_pnl")),
    }


def _first_number(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _optional_float(source.get(key))
        if value is not None:
            return value
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
