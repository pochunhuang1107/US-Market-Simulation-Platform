from __future__ import annotations

from typing import Any

import pandas as pd

from market_simulator.data.model_signals import validate_model_signal_frame
from market_simulator.engine.rotation import (
    RotationHolding,
    _is_rebalance_date,
    _price_at,
    _rebalance,
    _round,
    _symbol_frame,
    _weights_for_selection,
)
from market_simulator.models.result import SimulationResult
from market_simulator.reporting.metrics import (
    build_overlay_diagnostics,
    build_sleeve_summary,
    build_summary,
    build_yearly_report,
)


def _model_signal_symbols(strategy) -> list[str]:
    model_signal = strategy.model_signal
    symbols = set(model_signal.universe)
    if model_signal.fallback.type == "asset" and model_signal.fallback.symbol:
        symbols.add(model_signal.fallback.symbol)
    symbols.add(strategy.benchmark_symbol)
    return sorted(symbols)


def _portfolio_value(
    holdings: dict[str, RotationHolding],
    prices: dict[str, float],
    cash: float,
) -> float:
    return cash + sum(
        holding.shares * prices[symbol]
        for symbol, holding in holdings.items()
        if symbol in prices
    )


def _prepare_signal_frame(frame: pd.DataFrame, strategy) -> pd.DataFrame:
    model_signal = strategy.model_signal
    validated = validate_model_signal_frame(frame)
    if model_signal.ranking_field not in validated.columns:
        raise ValueError(
            f"model_signal ranking_field '{model_signal.ranking_field}' "
            "is not present in model signal frame"
        )

    prepared = validated.copy()
    prepared[model_signal.ranking_field] = pd.to_numeric(
        prepared[model_signal.ranking_field],
        errors="coerce",
    )
    if prepared[model_signal.ranking_field].isna().any():
        raise ValueError(
            f"model_signal ranking_field '{model_signal.ranking_field}' must be numeric"
        )
    return prepared


def _latest_available_signals(
    signal_frame: pd.DataFrame,
    strategy,
    date: pd.Timestamp,
) -> pd.DataFrame:
    model_signal = strategy.model_signal
    eligible = signal_frame[
        (signal_frame["model_version"] == model_signal.model_version)
        & (signal_frame["symbol"].isin(model_signal.universe))
        & (signal_frame["date"] <= date.normalize())
    ].copy()

    if model_signal.signal_bucket_filter:
        if "signal_bucket" not in eligible.columns:
            return eligible.iloc[0:0]
        eligible = eligible[
            eligible["signal_bucket"].astype("string").isin(
                model_signal.signal_bucket_filter
            )
        ]

    if model_signal.min_confidence is not None:
        if "confidence" not in eligible.columns:
            return eligible.iloc[0:0]
        eligible = eligible[
            eligible["confidence"].notna()
            & (eligible["confidence"] >= model_signal.min_confidence)
        ]

    if eligible.empty:
        return eligible

    return (
        eligible.sort_values(["symbol", "date"])
        .drop_duplicates(["symbol"], keep="last")
        .reset_index(drop=True)
    )


def _target_weights_from_signals(
    signal_frame: pd.DataFrame,
    strategy,
    date: pd.Timestamp,
) -> tuple[dict[str, float], dict[str, Any]]:
    model_signal = strategy.model_signal
    latest = _latest_available_signals(signal_frame, strategy, date)

    scores: dict[str, float] = {}
    signal_dates: dict[str, str] = {}
    if not latest.empty:
        scores = {
            str(row["symbol"]): _round(row[model_signal.ranking_field])
            for _, row in latest.iterrows()
        }
        signal_dates = {
            str(row["symbol"]): str(pd.Timestamp(row["date"]).date())
            for _, row in latest.iterrows()
        }

    ranked = sorted(scores.items(), key=lambda item: (-float(item[1]), item[0]))
    ranked_symbols = [symbol for symbol, _ in ranked]
    ranks = {symbol: rank for rank, symbol in enumerate(ranked_symbols, start=1)}

    selected_assets: list[str] = ranked_symbols[: model_signal.top_n]
    fallback_used: str | None = None
    if selected_assets:
        target_weights = _weights_for_selection(selected_assets, 1.0)
    elif model_signal.fallback.type == "asset" and model_signal.fallback.symbol:
        fallback_used = model_signal.fallback.symbol
        selected_assets = [model_signal.fallback.symbol]
        target_weights = {model_signal.fallback.symbol: 1.0}
    else:
        fallback_used = "cash"
        target_weights = {}

    return target_weights, {
        "risk_filter_passed": True,
        "fallback_used": fallback_used,
        "selected_assets": selected_assets,
        "asset_returns": scores,
        "asset_ranks": ranks,
        "risk_filter_signals": [],
        "rank_label": "Model signal rank",
        "signal_source": "model_signal",
        "snapshot_metadata_key": "model_signal",
        "model_scores": scores,
        "model_ranks": ranks,
        "model_signal_dates": signal_dates,
        "model_version": model_signal.model_version,
        "ranking_field": model_signal.ranking_field,
    }


def run_model_signal_simulation(bundle, strategy, model_signal_frame: pd.DataFrame) -> SimulationResult:
    model_signal = strategy.model_signal
    if model_signal is None or not model_signal.enabled:
        raise ValueError("model_signal strategy is not enabled")

    signal_frame = _prepare_signal_frame(model_signal_frame, strategy)
    df = bundle.tradable.reset_index(drop=True).copy()
    frames = {
        symbol: _symbol_frame(bundle, strategy, symbol).reset_index(drop=True)
        for symbol in _model_signal_symbols(strategy)
    }
    benchmark_df = _symbol_frame(bundle, strategy, strategy.benchmark_symbol)
    first_benchmark_close = _price_at(benchmark_df, pd.Timestamp(df.iloc[0]["date"]))
    if first_benchmark_close is None or first_benchmark_close == 0:
        raise ValueError("Benchmark close is unavailable on first simulation date")

    cash = float(strategy.initial_capital)
    holdings: dict[str, RotationHolding] = {}
    fees_paid = 0.0
    trade_log: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []

    current_target_weights: dict[str, float] = {}
    current_metadata: dict[str, Any] = {
        "fallback_used": None,
        "selected_assets": [],
        "asset_returns": {},
        "asset_ranks": {},
        "risk_filter_signals": [],
        "model_scores": {},
        "model_ranks": {},
        "model_signal_dates": {},
        "model_version": model_signal.model_version,
        "ranking_field": model_signal.ranking_field,
    }

    for index, row in df.iterrows():
        date = pd.Timestamp(row["date"])
        prices = {
            symbol: price
            for symbol, frame in frames.items()
            if (price := _price_at(frame, date)) is not None
        }
        rebalance = _is_rebalance_date(df, index, model_signal.rebalance.frequency)

        if rebalance:
            current_target_weights, current_metadata = _target_weights_from_signals(
                signal_frame,
                strategy,
                date,
            )
            cash, new_fees = _rebalance(
                date=date,
                prices=prices,
                cash=cash,
                holdings=holdings,
                target_weights=current_target_weights,
                cost_bps=strategy.transaction_cost_bps,
                trade_log=trade_log,
                snapshots=snapshots,
                metadata=current_metadata,
            )
            fees_paid += new_fees
            events.append(
                {
                    "date": str(date.date()),
                    "event_type": "MODEL_SIGNAL_REBALANCE",
                    "details": (
                        "Selected "
                        + (
                            ",".join(current_metadata["selected_assets"])
                            if current_metadata["selected_assets"]
                            else "cash"
                        )
                    ),
                }
            )

        holding_values = {
            symbol: holding.shares * prices[symbol]
            for symbol, holding in holdings.items()
            if symbol in prices and holding.shares > 0
        }
        position_market_value = sum(holding_values.values())
        total_equity = cash + position_market_value
        benchmark_close = _price_at(benchmark_df, date)
        benchmark_equity = (
            strategy.initial_capital * (benchmark_close / first_benchmark_close)
            if benchmark_close is not None
            else None
        )
        holdings_snapshot = {
            symbol: {
                "shares": holding.shares,
                "market_value": _round(holding_values.get(symbol, 0.0)),
                "weight_pct": _round((holding_values.get(symbol, 0.0) / total_equity) * 100)
                if total_equity
                else 0.0,
            }
            for symbol, holding in sorted(holdings.items())
            if holding.shares > 0
        }

        timeline_row = {
            "date": str(date.date()),
            "strategy_equity": round(total_equity, 6),
            "benchmark_equity": round(float(benchmark_equity), 6)
            if benchmark_equity is not None
            else None,
            "cash": round(cash, 6),
            "core_cash": 0.0,
            "core_shares": 0,
            "core_market_value": 0.0,
            "core_equity": 0.0,
            "core_fees_paid": 0.0,
            "overlay_cash": round(cash, 6),
            "overlay_position_shares": int(
                sum(holding.shares for holding in holdings.values())
            ),
            "overlay_position_market_value": round(position_market_value, 6),
            "overlay_avg_entry_price": 0.0,
            "overlay_equity": round(total_equity, 6),
            "overlay_realized_pnl": 0.0,
            "overlay_unrealized_pnl": round(
                total_equity - strategy.initial_capital + fees_paid,
                6,
            ),
            "overlay_fees_paid": round(fees_paid, 6),
            "core_pnl": 0.0,
            "overlay_pnl": round(total_equity - strategy.initial_capital, 6),
            "core_weight_pct": 0.0,
            "overlay_weight_pct": 100.0 if total_equity else 0.0,
            "current_profit_pct": 0.0,
            "entry_signal": False,
            "exit_signal": False,
            "cooldown_active": False,
            "action_taken": "rebalance" if rebalance else "",
            "minimum_trade_skip_reason": None,
            "rebalance": bool(rebalance),
            "selected_assets": current_metadata["selected_assets"],
            "target_weights": {
                symbol: _round(weight)
                for symbol, weight in current_target_weights.items()
            },
            "model_scores": current_metadata["model_scores"],
            "model_ranks": current_metadata["model_ranks"],
            "model_signal_dates": current_metadata["model_signal_dates"],
            "model_version": current_metadata["model_version"],
            "ranking_field": current_metadata["ranking_field"],
            "fallback_used": current_metadata["fallback_used"],
            "holdings": holdings_snapshot,
        }
        for symbol in model_signal.universe:
            holding = holdings.get(symbol, RotationHolding())
            value = holding_values.get(symbol, 0.0)
            timeline_row[f"holding_{symbol}_shares"] = int(holding.shares)
            timeline_row[f"holding_{symbol}_value"] = round(value, 6)
            timeline_row[f"weight_{symbol}_pct"] = (
                round((value / total_equity) * 100, 6) if total_equity else 0.0
            )
        timeline.append(timeline_row)

    tdf = pd.DataFrame(timeline)
    trades = pd.DataFrame(trade_log)

    summary = build_summary(tdf, trades, strategy)
    summary.update(
        {
            "strategy_type": "model_signal",
            "model_signal_universe": model_signal.universe,
            "model_signal_model_version": model_signal.model_version,
            "model_signal_ranking_field": model_signal.ranking_field,
            "model_signal_rebalance_frequency": model_signal.rebalance.frequency,
            "model_signal_top_n": model_signal.top_n,
            "rebalance_count": int(tdf["rebalance"].sum()) if "rebalance" in tdf else 0,
        }
    )
    sleeve_summary = build_sleeve_summary(tdf)
    overlay_diag = build_overlay_diagnostics(tdf, trades)
    yearly = build_yearly_report(tdf)

    return SimulationResult(
        summary=summary,
        sleeve_summary={
            **sleeve_summary,
            "overlay_diagnostics": overlay_diag,
        },
        yearly_report=yearly,
        trade_log=trade_log,
        timeline=timeline,
        events=events,
        trade_signal_snapshots=snapshots,
    )
