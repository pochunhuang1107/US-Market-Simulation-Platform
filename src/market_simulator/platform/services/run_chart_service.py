from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse

import boto3

from market_simulator.settings import get_settings


class RunChartService:
    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.s3 = boto3.client("s3", region_name=settings.artifact_s3_region)

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

    def _load_json(self, uri: str) -> dict:
        text = self._read_text(uri)
        return json.loads(text)

    def load_chart_data(self, artifact_manifest_json: dict[str, str]) -> dict:
        timeline_uri = artifact_manifest_json["timeline"]
        monthly_returns_uri = artifact_manifest_json["monthly_returns"]
        trade_log_uri = artifact_manifest_json["trade_log"]

        timeline_rows = self._load_csv_rows(timeline_uri)
        monthly_rows = self._load_csv_rows(monthly_returns_uri)
        trade_rows = self._load_csv_rows(trade_log_uri)

        equity_curve = []
        drawdown_curve = []
        sleeve_equity_curve = []
        sleeve_weight_curve = []
        trade_markers = []

        running_peak_strategy = None
        running_peak_benchmark = None

        for row in timeline_rows:
            date_value = row.get("date") or row.get("Date")
            strategy_equity = row.get("strategy_equity") or row.get("equity") or row.get("portfolio_equity")
            benchmark_equity = row.get("benchmark_equity")

            strategy_equity_value = (
                float(strategy_equity) if strategy_equity not in (None, "") else None
            )
            benchmark_equity_value = (
                float(benchmark_equity) if benchmark_equity not in (None, "") else None
            )

            core_equity = row.get("core_equity")
            overlay_equity = row.get("overlay_equity")

            core_weight = row.get("core_weight_pct")
            overlay_weight = row.get("overlay_weight_pct")

            core_equity_value = (
                float(core_equity) if core_equity not in (None, "") else None
            )
            overlay_equity_value = (
                float(overlay_equity) if overlay_equity not in (None, "") else None
            )

            if date_value and strategy_equity_value is not None:
                equity_curve.append(
                    {
                        "date": date_value,
                        "strategy_equity": strategy_equity_value,
                        "benchmark_equity": benchmark_equity_value,
                    }
                )

                sleeve_equity_curve.append(
                    {
                        "date": date_value,
                        "core_equity": core_equity_value,
                        "overlay_equity": overlay_equity_value,
                    }
                )

                sleeve_weight_curve.append(
                    {
                        "date": date_value,
                        "core_weight_pct": (
                            float(core_weight) if core_weight not in (None, "") else None
                        ),
                        "overlay_weight_pct": (
                            float(overlay_weight) if overlay_weight not in (None, "") else None
                        ),
                    }
                )

                if running_peak_strategy is None:
                    running_peak_strategy = strategy_equity_value
                else:
                    running_peak_strategy = max(running_peak_strategy, strategy_equity_value)

                strategy_drawdown_pct = (
                    (strategy_equity_value / running_peak_strategy) - 1.0
                ) * 100.0

                benchmark_drawdown_pct = None
                if benchmark_equity_value is not None:
                    if running_peak_benchmark is None:
                        running_peak_benchmark = benchmark_equity_value
                    else:
                        running_peak_benchmark = max(running_peak_benchmark, benchmark_equity_value)

                    benchmark_drawdown_pct = (
                        (benchmark_equity_value / running_peak_benchmark) - 1.0
                    ) * 100.0

                drawdown_curve.append(
                    {
                        "date": date_value,
                        "strategy_drawdown_pct": strategy_drawdown_pct,
                        "benchmark_drawdown_pct": benchmark_drawdown_pct,
                    }
                )

        monthly_returns = []
        for row in monthly_rows:
            month_value = row.get("month") or row.get("Month")
            return_pct = (
                row.get("strategy_return_pct")
                or row.get("return_pct")
                or row.get("monthly_return_pct")
            )

            if month_value and return_pct is not None:
                monthly_returns.append(
                    {
                        "month": month_value,
                        "return_pct": float(return_pct),
                    }
                )

        for row in trade_rows:
            date_value = row.get("date") or row.get("Date") or row.get("entry_date") or row.get("exit_date")
            side_value = row.get("side") or row.get("action") or row.get("signal")

            shares_value = (
                row.get("shares")
                or row.get("quantity")
                or row.get("position_shares")
            )

            price_value = (
                row.get("price")
                or row.get("fill_price")
                or row.get("entry_price")
                or row.get("exit_price")
            )

            reason_value = (
                row.get("reason")
                or row.get("exit_reason")
                or row.get("signal_reason")
            )

            if date_value and side_value:
                trade_markers.append(
                    {
                        "date": date_value,
                        "side": str(side_value),
                        "shares": float(shares_value) if shares_value not in (None, "") else None,
                        "price": float(price_value) if price_value not in (None, "") else None,
                        "reason": str(reason_value) if reason_value not in (None, "") else None,
                    }
                )

        return {
            "equity_curve": equity_curve,
            "drawdown_curve": drawdown_curve,
            "monthly_returns": monthly_returns,
            "sleeve_equity_curve": sleeve_equity_curve,
            "sleeve_weight_curve": sleeve_weight_curve,
            "trade_markers": trade_markers,
        }