from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3

from market_simulator.services.strategy_builder_summary import _describe_rule
from market_simulator.settings import get_settings


MAX_TRADE_EVENTS = 200
MAX_VALUES_ON_DATE = 12
REFERENCE_SERIES_LABELS = {"VIX", "VIX9D", "VXEEM", "DGS10", "DGS2", "T10Y2Y", "DFF"}


class TradeEventInspectorService:
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

    def _load_trade_signal_snapshots(self, uri: str | None) -> list[dict[str, Any]]:
        if not uri:
            return []
        try:
            payload = json.loads(self._read_text(uri))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def load_trade_events(
        self,
        artifact_manifest_json: dict[str, str],
        *,
        config: dict[str, Any] | None = None,
        limit: int = MAX_TRADE_EVENTS,
    ) -> dict[str, Any]:
        trade_log_uri = artifact_manifest_json["trade_log"]
        timeline_uri = artifact_manifest_json["timeline"]

        trade_rows = self._load_csv_rows(trade_log_uri)
        timeline_rows = self._load_csv_rows(timeline_uri)
        snapshots = self._load_trade_signal_snapshots(
            artifact_manifest_json.get("trade_signal_snapshots")
            or artifact_manifest_json.get("trade_signals")
        )
        snapshots_by_index = {
            event_index: snapshot
            for snapshot in snapshots
            if (event_index := _optional_int(snapshot.get("event_index"))) is not None
        }
        timeline_by_date = {
            normalized_date: row
            for row in timeline_rows
            if (normalized_date := _normalize_date(row.get("date") or row.get("Date")))
        }

        events = []
        for index, trade in enumerate(trade_rows[:limit]):
            date_value = _normalize_date(
                trade.get("date")
                or trade.get("Date")
                or trade.get("entry_date")
                or trade.get("exit_date")
            )
            timeline_row = timeline_by_date.get(date_value or "")
            action = str(
                trade.get("action")
                or trade.get("side")
                or trade.get("signal")
                or "TRADE"
            )
            values_on_date = _values_on_date(timeline_row or {})
            rule_summary = _rule_summary_for_event(action, timeline_row or {}, config)
            snapshot = snapshots_by_index.get(index)
            rule_context = (
                _rule_context_from_snapshot(snapshot)
                if snapshot is not None
                else _rule_context_for_event(action, timeline_row or {}, values_on_date, config)
            )
            capital_context = (
                _capital_context_from_snapshot(snapshot)
                if snapshot is not None
                else None
            )
            explanation = _explanation_for_event(
                action,
                timeline_row or {},
                values_on_date,
                rule_context,
            )

            events.append(
                {
                    "id": f"{date_value or 'trade'}-{index}",
                    "date": date_value,
                    "action": action,
                    "side": _side_for_action(action),
                    "price": _optional_float(
                        trade.get("price")
                        or trade.get("fill_price")
                        or trade.get("entry_price")
                        or trade.get("exit_price")
                    ),
                    "shares": _optional_float(
                        trade.get("shares")
                        or trade.get("quantity")
                        or trade.get("position_shares")
                    ),
                    "event_category": _event_category(action),
                    "values_on_date": values_on_date,
                    "rule_context": rule_context,
                    "capital_context": capital_context,
                    "rule_summary": rule_summary,
                    "explanation": explanation,
                }
            )

        return {
            "total_count": len(trade_rows),
            "events": events,
        }


def _normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None

    iso_candidate = text[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", iso_candidate):
        return iso_candidate

    for fmt in ("%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return iso_candidate if iso_candidate else None


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
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _coerce_value(value: Any) -> float | bool | str | None:
    bool_value = _optional_bool(value)
    if bool_value is not None:
        return bool_value

    float_value = _optional_float(value)
    if float_value is not None:
        return round(float_value, 6)

    if value in (None, ""):
        return None
    return str(value)


def _column_priority(column: str) -> int:
    lowered = column.lower()
    if lowered in {"signal_series_vix", "vix", "close_vix", "vix_value"}:
        return 0
    if "rsi" in lowered and "threshold" not in lowered:
        return 1
    if "sma" in lowered:
        return 2
    if "macd" in lowered:
        return 3
    if lowered in {"k", "d"} or lowered.startswith(("kd_", "stoch_")):
        return 4
    if lowered in {"close", "price"} or lowered.endswith("_close") or lowered.endswith("_price"):
        return 8
    if "threshold" in lowered:
        return 9
    if lowered.startswith("signal_series_") or lowered.startswith("reference_"):
        return 6
    if lowered.endswith("_value"):
        return 6
    if "realized_volatility" in lowered or lowered.startswith("return_"):
        return 7
    return 99


def _is_relevant_value_column(column: str) -> bool:
    lowered = column.lower()
    if lowered in {
        "date",
        "strategy_equity",
        "benchmark_equity",
        "cash",
        "core_cash",
        "core_shares",
        "core_market_value",
        "core_equity",
        "core_fees_paid",
        "overlay_cash",
        "overlay_position_shares",
        "overlay_position_market_value",
        "overlay_avg_entry_price",
        "overlay_equity",
        "overlay_realized_pnl",
        "overlay_unrealized_pnl",
        "overlay_fees_paid",
        "core_pnl",
        "overlay_pnl",
        "core_weight_pct",
        "overlay_weight_pct",
        "current_profit_pct",
        "entry_signal",
        "exit_signal",
        "cooldown_active",
        "action_taken",
        "tradable_symbol",
        "symbol",
    }:
        return False

    tokens = (
        "rsi",
        "vix",
        "sma",
        "macd",
        "signal_series_",
        "reference_",
        "realized_volatility",
        "return_",
        "close",
        "price",
    )
    return (
        lowered in {"k", "d", "kd", "stochastic"}
        or lowered.startswith(("kd_", "stoch_"))
        or lowered.endswith("_value")
        or any(token in lowered for token in tokens)
    )


def _label_for_column(column: str) -> str:
    lowered = column.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")

    if lowered.startswith("signal_series_"):
        remainder = column[len("signal_series_"):]
        return _humanize_column(remainder)

    if lowered.startswith("reference_"):
        remainder = column[len("reference_"):]
        return _label_for_column(remainder)

    if normalized.startswith("signal_rsi_"):
        lookback = normalized[len("signal_rsi_"):]
        return f"RSI({lookback})"

    if normalized.startswith("rsi_"):
        lookback = normalized[len("rsi_"):]
        return f"RSI({lookback})"

    rsi_match = re.search(r"(?:^|_)(?:[a-z0-9]+_)?rsi_?(\d+)?$", normalized)
    if rsi_match:
        lookback = rsi_match.group(1) or "14"
        return f"RSI({lookback})"

    rsi_compact_match = re.search(r"rsi(\d+)$", normalized)
    if rsi_compact_match:
        return f"RSI({rsi_compact_match.group(1)})"

    if normalized.startswith("sma_"):
        window = normalized[len("sma_"):]
        return f"SMA({window})"

    sma_match = re.search(r"(?:^|_)sma_?(\d+)$", normalized)
    if sma_match:
        return f"SMA({sma_match.group(1)})"

    if normalized.startswith("realized_volatility_"):
        lookback = normalized[len("realized_volatility_"):]
        return f"Realized Volatility({lookback})"

    realized_match = re.search(r"(?:^|_)realized_volatility_?(\d+)$", normalized)
    if realized_match:
        return f"Realized Volatility({realized_match.group(1)})"

    if normalized.startswith("return_"):
        lookback = normalized[len("return_"):]
        return f"Return({lookback})"

    if normalized in {"macd", "macd_line"} or (normalized.endswith("_macd") and "signal" not in normalized and "hist" not in normalized):
        return "MACD"
    if normalized in {"macd_signal", "macd_signal_line"} or normalized.endswith("_macd_signal"):
        return "MACD signal"
    if normalized in {"macd_hist", "macd_histogram"} or normalized.endswith("_macd_hist"):
        return "MACD histogram"

    if normalized in {"k", "kd_k", "stoch_k", "stochastic_k"} or normalized.endswith("_kd_k"):
        return "KD K"
    if normalized in {"d", "kd_d", "stoch_d", "stochastic_d"} or normalized.endswith("_kd_d"):
        return "KD D"
    if normalized in {"kd", "stochastic"}:
        return "KD"

    for suffix in ("_value", "_close", "_price"):
        if lowered.endswith(suffix):
            prefix = column[: -len(suffix)]
            if prefix.upper() in REFERENCE_SERIES_LABELS:
                return prefix.upper()
            return f"{_humanize_column(prefix)} {suffix[1:].title()}"

    for prefix in ("close_", "price_"):
        if lowered.startswith(prefix):
            symbol = column[len(prefix):]
            if symbol.upper() in REFERENCE_SERIES_LABELS:
                return symbol.upper()
            return f"{_humanize_column(symbol)} {prefix[:-1].title()}"

    if normalized in {"close", "price"}:
        return lowered.title()

    return _humanize_column(column)


def _humanize_column(value: str) -> str:
    if value.upper() in REFERENCE_SERIES_LABELS:
        return value.upper()
    if value.isupper() and value.isalnum() and len(value) <= 5:
        return value
    return value.replace("_", " ").strip().title()


def _values_on_date(timeline_row: dict[str, str]) -> dict[str, float | bool | str]:
    candidates: list[tuple[int, str, float | bool | str]] = []
    for column, raw_value in timeline_row.items():
        if not _is_relevant_value_column(column):
            continue
        value = _coerce_value(raw_value)
        if value is None:
            continue
        candidates.append((_column_priority(column), _label_for_column(column), value))

    candidates.sort(key=lambda item: (item[0], item[1]))

    values: dict[str, float | bool | str] = {}
    for _, label, value in candidates:
        if label in values:
            continue
        values[label] = value
        if len(values) >= MAX_VALUES_ON_DATE:
            break

    return values


def _side_for_action(action: str) -> str:
    upper = action.upper()
    if upper.startswith("BUY"):
        return "BUY"
    if upper.startswith("SELL"):
        return "SELL"
    return upper


def _event_category(action: str) -> str:
    upper = action.upper()
    if upper.startswith("BUY"):
        return "entry"
    if "STOP_LOSS" in upper or "TAKE_PROFIT" in upper:
        return "risk"
    if "REDUCE" in upper:
        return "reduce"
    if upper.startswith("SELL"):
        return "exit"
    return "trade"


def _rule_summary_for_event(
    action: str,
    timeline_row: dict[str, str],
    config: dict[str, Any] | None,
) -> str | None:
    if not isinstance(config, dict):
        return None

    tradable_symbol = config.get("tradable_symbol") or config.get("symbol")
    category = _event_category(action)
    upper = action.upper()
    entry_rule = _normalize_rule(config.get("entry_rule") or config.get("entry"))
    exit_rule = _normalize_rule(config.get("exit_rule") or config.get("exit"))

    if category == "entry":
        return f"Entry rule: {_describe_rule(entry_rule, tradable_symbol)}"

    if "STOP_LOSS" in upper:
        stop_loss = (config.get("risk") or {}).get("stop_loss_pct")
        return f"Risk rule: stop loss at {float(stop_loss) * 100:g}%" if stop_loss is not None else "Risk rule: stop loss"

    if "TAKE_PROFIT" in upper:
        take_profit = (config.get("risk") or {}).get("take_profit_pct")
        return (
            f"Risk rule: take profit at {float(take_profit) * 100:g}%"
            if take_profit is not None
            else "Risk rule: take profit"
        )

    if "REDUCE_PROFIT" in upper:
        threshold = (config.get("position_management") or {}).get("profit_reduce_threshold")
        return (
            f"Position management: reduce after profit exceeds {float(threshold) * 100:g}%"
            if threshold is not None
            else "Position management: profit reduction"
        )

    if category in {"exit", "reduce"} and _optional_bool(timeline_row.get("exit_signal")) is not False:
        return f"Exit rule: {_describe_rule(exit_rule, tradable_symbol)}"

    if _optional_bool(timeline_row.get("entry_signal")):
        return f"Entry rule: {_describe_rule(entry_rule, tradable_symbol)}"
    if _optional_bool(timeline_row.get("exit_signal")):
        return f"Exit rule: {_describe_rule(exit_rule, tradable_symbol)}"

    return None


def _normalize_rule(rule: Any) -> dict | None:
    if not isinstance(rule, dict):
        return None
    if "kind" in rule:
        return rule
    if "type" in rule:
        return {"kind": "atomic", **rule}
    return rule


def _collect_atomic_rules(rule: Any) -> list[dict[str, Any]]:
    if not isinstance(rule, dict):
        return []

    normalized = _normalize_rule(rule)
    if not isinstance(normalized, dict):
        return []

    kind = normalized.get("kind")
    if kind == "atomic":
        return [normalized]
    if kind == "not":
        return _collect_atomic_rules(normalized.get("rule"))
    if kind == "group":
        rules: list[dict[str, Any]] = []
        for child in normalized.get("rules", []):
            rules.extend(_collect_atomic_rules(child))
        return rules
    if kind == "window":
        return _collect_atomic_rules(normalized.get("rule"))
    if kind == "sequence":
        rules: list[dict[str, Any]] = []
        for step in normalized.get("steps", []):
            rules.extend(_collect_atomic_rules(step))
        return rules
    return []


def _rules_for_event(action: str, timeline_row: dict[str, str], config: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(config, dict):
        return []

    category = _event_category(action)
    if category == "entry":
        return _collect_atomic_rules(config.get("entry_rule") or config.get("entry"))
    if category in {"exit", "reduce"}:
        return _collect_atomic_rules(config.get("exit_rule") or config.get("exit"))

    if _optional_bool(timeline_row.get("entry_signal")):
        return _collect_atomic_rules(config.get("entry_rule") or config.get("entry"))
    if _optional_bool(timeline_row.get("exit_signal")):
        return _collect_atomic_rules(config.get("exit_rule") or config.get("exit"))
    return []


def _first_value(values_on_date: dict[str, float | bool | str], labels: list[str]) -> tuple[str | None, float | bool | str | None]:
    by_normalized = {_normalize_label(label): (label, value) for label, value in values_on_date.items()}
    for label in labels:
        match = by_normalized.get(_normalize_label(label))
        if match is not None:
            return match
    return None, None


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", label.lower())


def _rule_symbol(rule: dict[str, Any], config: dict[str, Any] | None) -> str:
    symbol = rule.get("symbol")
    if not symbol and isinstance(config, dict):
        symbol = config.get("tradable_symbol") or config.get("symbol")
    return str(symbol or "").upper()


def _compare_result(actual: Any, operator: str | None, threshold: Any) -> str:
    if actual is None or threshold is None or operator not in {"below", "above"}:
        return "unknown"
    try:
        actual_float = float(actual)
        threshold_float = float(threshold)
    except (TypeError, ValueError):
        return "unknown"

    if operator == "below":
        return "matched" if actual_float < threshold_float else "not_matched"
    return "matched" if actual_float > threshold_float else "not_matched"


def _rule_context_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    signals = snapshot.get("signals")
    if not isinstance(signals, list):
        return contexts

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        actual_value = _coerce_value(
            signal.get("actual_value") if "actual_value" in signal else signal.get("actual")
        )
        threshold = _coerce_value(signal.get("threshold"))
        status = str(signal.get("status") or "").strip() or "unavailable"
        if actual_value is None:
            status = "unavailable"

        label = str(signal.get("label") or "Signal")
        contexts.append(
            {
                "label": label,
                "summary": label,
                "actual_label": label if actual_value is not None else None,
                "actual_value": actual_value,
                "operator": signal.get("operator"),
                "threshold": threshold,
                "result": status,
                "status": status,
                "source": signal.get("source"),
                "limitation": (
                    "Actual value was not present in signal snapshot for this date."
                    if actual_value is None
                    else None
                ),
            }
        )

    return contexts


def _capital_context_from_snapshot(snapshot: dict[str, Any]) -> dict[str, float | int] | None:
    raw_context = snapshot.get("capital_context")
    if not isinstance(raw_context, dict):
        return None

    context: dict[str, float | int] = {}
    integer_fields = {"position_shares_before", "position_shares_after"}
    for key, value in raw_context.items():
        if key in integer_fields:
            int_value = _optional_int(value)
            if int_value is not None:
                context[key] = int_value
            continue

        float_value = _optional_float(value)
        if float_value is not None:
            context[key] = round(float_value, 6)

    return context or None


def _rule_context_for_event(
    action: str,
    timeline_row: dict[str, str],
    values_on_date: dict[str, float | bool | str],
    config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for rule in _rules_for_event(action, timeline_row, config):
        context = _rule_context_for_atomic_rule(rule, values_on_date, config)
        if context is not None:
            contexts.append(context)
    return contexts


def _rule_context_for_atomic_rule(
    rule: dict[str, Any],
    values_on_date: dict[str, float | bool | str],
    config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    rule_type = str(rule.get("type") or "")
    symbol = _rule_symbol(rule, config)
    threshold = rule.get("threshold")
    operator: str | None = None
    actual_label: str | None = None
    actual_value: float | bool | str | None = None
    threshold_value: Any = threshold
    label = _describe_rule(rule, symbol or None)

    if rule_type in {"rsi_below", "rsi_above"}:
        lookback = rule.get("lookback") or 14
        operator = "below" if rule_type.endswith("below") else "above"
        label = f"{symbol} RSI({lookback})" if symbol else f"RSI({lookback})"
        actual_label, actual_value = _first_value(values_on_date, [f"{symbol} RSI({lookback})", f"RSI({lookback})"])
    elif rule_type in {"series_below", "series_above"}:
        operator = "below" if rule_type.endswith("below") else "above"
        label = symbol or str(rule.get("symbol") or "Series").upper()
        actual_label, actual_value = _first_value(values_on_date, [label, f"{label} Close", f"{label} Price"])
    elif rule_type in {"realized_volatility_below", "realized_volatility_above"}:
        lookback = rule.get("lookback")
        operator = "below" if rule_type.endswith("below") else "above"
        label = f"{symbol} realized volatility({lookback})" if symbol else f"Realized volatility({lookback})"
        actual_label, actual_value = _first_value(
            values_on_date,
            [f"{symbol} Realized Volatility({lookback})", f"Realized Volatility({lookback})"],
        )
    elif rule_type in {"sma_above", "sma_cross_above", "sma_cross_below"}:
        fast_window = rule.get("fast_window")
        slow_window = rule.get("slow_window")
        operator = "above" if rule_type.endswith("above") else "below"
        actual_candidates = [f"{symbol} Close", f"{symbol} Price", "Close", "Price"] if fast_window == 1 else [f"SMA({fast_window})"]
        actual_label, actual_value = _first_value(values_on_date, actual_candidates)
        _, threshold_value = _first_value(values_on_date, [f"SMA({slow_window})"])
        label = f"{symbol} Price" if fast_window == 1 and symbol else f"SMA({fast_window})"
    elif rule_type in {"macd_bullish_cross", "macd_bearish_cross"}:
        operator = "above" if rule_type == "macd_bullish_cross" else "below"
        actual_label, actual_value = _first_value(values_on_date, ["MACD"])
        _, signal_value = _first_value(values_on_date, ["MACD signal"])
        threshold_value = signal_value
        label = f"{symbol} MACD" if symbol else "MACD"
    elif rule_type in {"kd_golden_cross", "kd_dead_cross"}:
        operator = "above" if rule_type == "kd_golden_cross" else "below"
        actual_label, actual_value = _first_value(values_on_date, ["KD K", "KD"])
        _, threshold_value = _first_value(values_on_date, ["KD D"])
        label = f"{symbol} KD/stochastic" if symbol else "KD/stochastic"
    elif rule_type in {
        "bullish_candle",
        "bearish_candle",
        "close_above_previous_high",
        "close_below_previous_low",
        "close_near_high",
        "close_near_low",
    }:
        actual_label, actual_value = _first_value(values_on_date, ["Close", "Price"])
        label = _describe_rule(rule, symbol or None)
    else:
        return None

    result = _compare_result(actual_value, operator, threshold_value)
    limitation = None
    if actual_value is None:
        limitation = "Actual value was not present in timeline artifacts for this date."
        result = "unavailable"
    elif threshold_value is None:
        limitation = "Comparable threshold value was not present in artifacts for this date."

    return {
        "label": label,
        "summary": _describe_rule(rule, symbol or None),
        "actual_label": actual_label,
        "actual_value": actual_value,
        "operator": operator,
        "threshold": threshold_value,
        "result": result,
        "limitation": limitation,
    }


def _format_value(value: float | bool | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _available_values_text(values_on_date: dict[str, float | bool | str]) -> str:
    if not values_on_date:
        return "No signal values were found in artifacts for this trade date."

    values = ", ".join(
        f"{label} {_format_value(value)}"
        for label, value in values_on_date.items()
    )
    return f"Signal values: {values}."


def _explanation_for_event(
    action: str,
    timeline_row: dict[str, str],
    values_on_date: dict[str, float | bool | str],
    rule_context: list[dict[str, Any]],
) -> str:
    return _available_values_text(values_on_date)
