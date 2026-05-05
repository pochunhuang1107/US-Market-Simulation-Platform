from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3

from market_simulator.services.strategy_builder_summary import _describe_rule
from market_simulator.settings import get_settings


MAX_TRADE_EVENTS = 200
MAX_VALUES_ON_DATE = 12


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
            explanation = _explanation_for_event(
                action,
                timeline_row or {},
                values_on_date,
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
    text = str(value).strip()
    return text[:10] if text else None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
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
    if lowered in {"signal_series_vix", "vix", "close_vix"}:
        return 0
    if "rsi" in lowered and "threshold" not in lowered:
        return 1
    if "sma" in lowered:
        return 2
    if "macd" in lowered:
        return 3
    if lowered in {"k", "d"} or lowered.startswith("kd_"):
        return 4
    if "threshold" in lowered:
        return 5
    if lowered.startswith("signal_series_") or lowered.startswith("reference_"):
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
    )
    return lowered in {"k", "d"} or lowered.startswith("kd_") or any(token in lowered for token in tokens)


def _label_for_column(column: str) -> str:
    lowered = column.lower()

    if lowered.startswith("signal_series_"):
        remainder = column[len("signal_series_"):]
        return _humanize_column(remainder)

    if lowered.startswith("signal_rsi_"):
        lookback = column[len("signal_rsi_"):]
        return f"RSI({lookback})"

    if lowered.startswith("rsi_"):
        lookback = column[len("rsi_"):]
        return f"RSI({lookback})"

    if lowered.startswith("sma_"):
        window = column[len("sma_"):]
        return f"SMA({window})"

    if lowered == "macd":
        return "MACD"
    if lowered == "macd_signal":
        return "MACD signal"
    if lowered == "macd_hist":
        return "MACD histogram"

    if lowered == "k":
        return "KD K"
    if lowered == "d":
        return "KD D"

    return _humanize_column(column)


def _humanize_column(value: str) -> str:
    if value.upper() in {"VIX", "VIX9D", "VXEEM", "DGS10", "DGS2", "T10Y2Y", "DFF"}:
        return value.upper()
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


def _format_value(value: float | bool | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _available_values_text(values_on_date: dict[str, float | bool | str]) -> str:
    if not values_on_date:
        return "No indicator/reference values were available in artifacts for this date."

    values = ", ".join(
        f"{label} {_format_value(value)}"
        for label, value in values_on_date.items()
    )
    return f"Available values: {values}."


def _explanation_for_event(
    action: str,
    timeline_row: dict[str, str],
    values_on_date: dict[str, float | bool | str],
) -> str:
    category = _event_category(action)
    values_text = _available_values_text(values_on_date)
    upper = action.upper()

    if category == "entry" and _optional_bool(timeline_row.get("entry_signal")) is not False:
        return f"Matched entry rule. {values_text}"

    if "STOP_LOSS" in upper or "TAKE_PROFIT" in upper:
        return f"Matched risk control. {values_text}"

    if category in {"exit", "reduce"} and _optional_bool(timeline_row.get("exit_signal")) is not False:
        return f"Matched exit rule. {values_text}"

    return (
        "Rule context is shown from available artifact values; exact trigger attribution may be limited. "
        f"{values_text}"
    )
