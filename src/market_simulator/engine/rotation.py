from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from market_simulator.engine.execution import transaction_cost
from market_simulator.models.result import SimulationResult
from market_simulator.reporting.metrics import (
    build_overlay_diagnostics,
    build_sleeve_summary,
    build_summary,
    build_yearly_report,
)
from market_simulator.strategy.dataframe_resolution import (
    resolve_market_dataframe,
    row_position_for_date,
)
from market_simulator.strategy.enricher import enrich_market_data
from market_simulator.strategy.evaluator import evaluate_rule


@dataclass
class RotationHolding:
    shares: int = 0
    avg_entry_price: float = 0.0


def _round(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _price_at(df: pd.DataFrame, date: pd.Timestamp) -> float | None:
    row_pos = row_position_for_date(df, date)
    if row_pos is None:
        return None
    close = df.iloc[row_pos]["close"]
    if pd.isna(close):
        return None
    return float(close)


def _symbol_frame(bundle, strategy, symbol: str) -> pd.DataFrame:
    return resolve_market_dataframe(bundle, symbol, strategy.tradable_symbol)


def _rotation_symbols(strategy) -> list[str]:
    rotation = strategy.rotation
    symbols = set(rotation.universe)
    if rotation.fallback.type == "asset" and rotation.fallback.symbol:
        symbols.add(rotation.fallback.symbol)
    symbols.add(strategy.benchmark_symbol)
    return sorted(symbols)


def _is_rebalance_date(df: pd.DataFrame, index: int, frequency: str) -> bool:
    if index == 0:
        return True

    current = pd.Timestamp(df.iloc[index]["date"])
    previous = pd.Timestamp(df.iloc[index - 1]["date"])

    if frequency == "monthly":
        return (current.year, current.month) != (previous.year, previous.month)
    if frequency == "weekly":
        current_week = current.isocalendar()
        previous_week = previous.isocalendar()
        return (current_week.year, current_week.week) != (
            previous_week.year,
            previous_week.week,
        )
    if frequency == "quarterly":
        current_quarter = (current.month - 1) // 3
        previous_quarter = (previous.month - 1) // 3
        return (current.year, current_quarter) != (previous.year, previous_quarter)

    raise ValueError(f"Unsupported rotation rebalance frequency: {frequency}")


def _relative_return_at(
    df: pd.DataFrame,
    date: pd.Timestamp,
    lookback: int,
) -> float | None:
    row_pos = row_position_for_date(df, date)
    if row_pos is None:
        return None

    lookback_pos = row_pos - lookback
    if lookback_pos < 0:
        return None

    prior_close = df.iloc[lookback_pos]["close"]
    close = df.iloc[row_pos]["close"]
    if pd.isna(prior_close) or pd.isna(close) or float(prior_close) == 0:
        return None

    return float(close) / float(prior_close) - 1.0


def _rank_universe(bundle, strategy, date: pd.Timestamp) -> tuple[list[str], dict[str, float], dict[str, int]]:
    rotation = strategy.rotation
    returns: dict[str, float] = {}
    for symbol in rotation.universe:
        symbol_return = _relative_return_at(
            _symbol_frame(bundle, strategy, symbol),
            date,
            rotation.ranking.lookback,
        )
        if symbol_return is not None:
            returns[symbol] = symbol_return

    ranked = sorted(
        returns.items(),
        key=lambda item: (-item[1] if rotation.ranking.descending else item[1], item[0]),
    )
    ranked_symbols = [symbol for symbol, _ in ranked]
    ranks = {symbol: rank for rank, symbol in enumerate(ranked_symbols, start=1)}
    return ranked_symbols, returns, ranks


def _weights_for_selection(selected: list[str], max_position_pct: float) -> dict[str, float]:
    if not selected:
        return {}

    equal_weight = min(max_position_pct, 1.0 / len(selected))
    return {symbol: equal_weight for symbol in selected}


def _target_weights(
    bundle,
    strategy,
    index: int,
    date: pd.Timestamp,
) -> tuple[dict[str, float], dict[str, Any]]:
    rotation = strategy.rotation
    risk_passed = True
    if rotation.risk_filter is not None:
        risk_passed = evaluate_rule(
            rotation.risk_filter,
            bundle,
            index,
            strategy.tradable_symbol,
        )

    ranked_symbols, asset_returns, ranks = _rank_universe(bundle, strategy, date)
    selected_assets: list[str] = []
    target_weights: dict[str, float] = {}
    fallback_used: str | None = None

    if risk_passed:
        selected_assets = ranked_symbols[: rotation.selection.top_n]
        target_weights = _weights_for_selection(
            selected_assets,
            rotation.allocation.max_position_pct,
        )
    elif rotation.fallback.type == "asset" and rotation.fallback.symbol:
        fallback_used = rotation.fallback.symbol
        selected_assets = [rotation.fallback.symbol]
        target_weights = {
            rotation.fallback.symbol: min(rotation.allocation.max_position_pct, 1.0)
        }
    else:
        fallback_used = "cash"

    return target_weights, {
        "risk_filter_passed": risk_passed,
        "fallback_used": fallback_used,
        "selected_assets": selected_assets,
        "asset_returns": {symbol: _round(value) for symbol, value in asset_returns.items()},
        "asset_ranks": ranks,
    }


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


def _record_rotation_trade_snapshot(
    snapshots: list[dict[str, Any]],
    trade: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    event_index = len(snapshots)
    snapshots.append(
        {
            "id": f"{trade.get('date') or 'trade'}-{event_index}",
            "event_index": event_index,
            "date": str(trade.get("date") or ""),
            "action": str(trade.get("action") or "TRADE"),
            "side": "BUY" if str(trade.get("action", "")).startswith("BUY") else "SELL",
            "price": trade.get("price"),
            "shares": trade.get("shares"),
            "symbol": trade.get("symbol"),
            "signals": [
                {
                    "label": "Rotation rank",
                    "actual": metadata.get("asset_ranks", {}).get(trade.get("symbol")),
                    "actual_value": metadata.get("asset_returns", {}).get(trade.get("symbol")),
                    "source": "rotation",
                    "status": "selected"
                    if trade.get("symbol") in metadata.get("selected_assets", [])
                    else "rebalanced",
                }
            ],
            "rotation": metadata,
        }
    )


def _rebalance(
    *,
    date: pd.Timestamp,
    prices: dict[str, float],
    cash: float,
    holdings: dict[str, RotationHolding],
    target_weights: dict[str, float],
    cost_bps: float,
    trade_log: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> tuple[float, float]:
    equity_before = _portfolio_value(holdings, prices, cash)
    fees_paid = 0.0
    target_shares: dict[str, int] = {}

    for symbol, target_weight in target_weights.items():
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue
        target_shares[symbol] = int((equity_before * target_weight) // price)

    for symbol in sorted(list(holdings)):
        holding = holdings[symbol]
        price = prices.get(symbol)
        if price is None or holding.shares <= 0:
            continue

        desired = target_shares.get(symbol, 0)
        shares_to_sell = holding.shares - desired
        if shares_to_sell <= 0:
            continue

        notional = shares_to_sell * price
        fee = transaction_cost(notional, cost_bps)
        gross_pnl = (price - holding.avg_entry_price) * shares_to_sell
        net_pnl = gross_pnl - fee
        cash += notional - fee
        fees_paid += fee
        holding.shares -= shares_to_sell
        if holding.shares == 0:
            holding.avg_entry_price = 0.0

        trade = {
            "date": str(date.date()),
            "action": "SELL_ALL" if desired == 0 else "SELL_REDUCE",
            "symbol": symbol,
            "shares": shares_to_sell,
            "price": round(price, 6),
            "gross_pnl": round(gross_pnl, 6),
            "net_pnl": round(net_pnl, 6),
            "fee": round(fee, 6),
            "sleeve": "rotation",
        }
        trade_log.append(trade)
        _record_rotation_trade_snapshot(snapshots, trade, metadata)

    for symbol in sorted(target_shares):
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue

        holding = holdings.setdefault(symbol, RotationHolding())
        shares_to_buy = target_shares[symbol] - holding.shares
        if shares_to_buy <= 0:
            continue

        cost_multiplier = 1.0 + (cost_bps / 10000.0)
        affordable_shares = int(cash // (price * cost_multiplier))
        shares_to_buy = min(shares_to_buy, affordable_shares)
        if shares_to_buy <= 0:
            continue

        notional = shares_to_buy * price
        fee = transaction_cost(notional, cost_bps)
        total_cost = notional + fee
        cash -= total_cost
        fees_paid += fee

        existing_shares = holding.shares
        new_shares = existing_shares + shares_to_buy
        holding.avg_entry_price = (
            (
                existing_shares * holding.avg_entry_price
                + shares_to_buy * price
            )
            / new_shares
            if new_shares > 0
            else 0.0
        )
        holding.shares = new_shares

        trade = {
            "date": str(date.date()),
            "action": "BUY_ADD" if existing_shares > 0 else "BUY",
            "symbol": symbol,
            "shares": shares_to_buy,
            "price": round(price, 6),
            "fee": round(fee, 6),
            "sleeve": "rotation",
        }
        trade_log.append(trade)
        _record_rotation_trade_snapshot(snapshots, trade, metadata)

    return cash, fees_paid


def run_rotation_simulation(bundle, strategy) -> SimulationResult:
    bundle = enrich_market_data(bundle, strategy)
    df = bundle.tradable.reset_index(drop=True).copy()
    rotation = strategy.rotation
    if rotation is None or not rotation.enabled:
        raise ValueError("rotation strategy is not enabled")

    frames = {
        symbol: _symbol_frame(bundle, strategy, symbol).reset_index(drop=True)
        for symbol in _rotation_symbols(strategy)
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
        "risk_filter_passed": True,
        "fallback_used": None,
        "selected_assets": [],
        "asset_returns": {},
        "asset_ranks": {},
    }

    for index, row in df.iterrows():
        date = pd.Timestamp(row["date"])
        prices = {
            symbol: price
            for symbol, frame in frames.items()
            if (price := _price_at(frame, date)) is not None
        }
        rebalance = _is_rebalance_date(df, index, rotation.rebalance.frequency)

        if rebalance:
            current_target_weights, current_metadata = _target_weights(
                bundle,
                strategy,
                index,
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
                    "event_type": "ROTATION_REBALANCE",
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
            "asset_returns": current_metadata["asset_returns"],
            "asset_ranks": current_metadata["asset_ranks"],
            "risk_filter_passed": current_metadata["risk_filter_passed"],
            "fallback_used": current_metadata["fallback_used"],
            "holdings": holdings_snapshot,
        }
        for symbol in rotation.universe:
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
            "strategy_type": "rotation",
            "rotation_universe": rotation.universe,
            "rotation_ranking_type": rotation.ranking.type,
            "rotation_lookback": rotation.ranking.lookback,
            "rotation_rebalance_frequency": rotation.rebalance.frequency,
            "rotation_top_n": rotation.selection.top_n,
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
