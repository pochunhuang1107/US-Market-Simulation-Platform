from __future__ import annotations

import pandas as pd

from market_simulator.engine.execution import transaction_cost
from market_simulator.engine.portfolio import PortfolioState
from market_simulator.models.result import SimulationResult
from market_simulator.reporting.metrics import (
    build_summary,
    build_sleeve_summary,
    build_yearly_report,
    build_overlay_diagnostics,
)
from market_simulator.strategy.enricher import enrich_market_data
from market_simulator.strategy.evaluator import evaluate_rule


def _benchmark_curve(df, initial_capital):
    return initial_capital * (df["close"] / float(df["close"].iloc[0]))


def _sell_overlay(portfolio: PortfolioState, shares: int, price: float, cost_bps: float):
    notional = shares * price
    fee = transaction_cost(notional, cost_bps)
    gross = (price - portfolio.position.avg_entry_price) * shares
    net = gross - fee

    portfolio.overlay_cash += notional - fee
    portfolio.overlay_realized_pnl += net
    portfolio.overlay_fees_paid += fee
    portfolio.position.shares -= shares

    if portfolio.position.shares == 0:
        portfolio.position.avg_entry_price = 0.0
        portfolio.position.partial_take_profit_count = 0

    return gross, net, fee


def run_simulation(bundle, strategy):
    bundle = enrich_market_data(bundle, strategy)
    df = bundle.tradable.reset_index(drop=True).copy()
    bench = _benchmark_curve(df, strategy.initial_capital)

    core_allocation_pct = (
        strategy.core_overlay.core_allocation_pct
        if strategy.core_overlay.enabled
        else 0.0
    )

    core_budget = strategy.initial_capital * core_allocation_pct
    overlay_budget = strategy.initial_capital - core_budget

    portfolio = PortfolioState(
        core_cash=core_budget,
        overlay_cash=overlay_budget,
        core_initial_capital=core_budget,
        overlay_initial_capital=overlay_budget,
    )

    first_close = float(df["close"].iloc[0])

    # initialize core sleeve
    if strategy.core_overlay.enabled and core_budget > 0:
        core_shares = int(core_budget // first_close)
        core_notional = core_shares * first_close
        core_fee = transaction_cost(core_notional, strategy.transaction_cost_bps)

        if core_notional + core_fee <= portfolio.core_cash:
            portfolio.core_cash -= (core_notional + core_fee)
            portfolio.core_shares = core_shares
            portfolio.core_entry_price = first_close
            portfolio.core_fees_paid += core_fee

    trade_log = []
    timeline = []
    events = []

    for i, row in df.iterrows():
        date = pd.Timestamp(row["date"])
        close = float(row["close"])

        entry_signal = evaluate_rule(strategy.entry_rule, bundle, i)
        exit_signal = evaluate_rule(strategy.exit_rule, bundle, i)
        action = ""

        # === POSITION MANAGEMENT CONFIG (NEW) ===
        pm = getattr(strategy, "position_management", None)

        scale_in_fraction = pm.scale_in_fraction if pm else 0.25
        scale_out_fraction = pm.scale_out_fraction if pm else 0.5
        profit_reduce_threshold = pm.profit_reduce_threshold if pm else 0.05

        # risk / exits for overlay sleeve only
        if portfolio.position.in_position and action == "":
            # === EARLY PROFIT REDUCE (NEW) ===
            profit_pct = close / portfolio.position.avg_entry_price - 1.0

            if (
                profit_pct > profit_reduce_threshold
                and action == ""
                and portfolio.position.shares > 1
            ):
                shares = max(1, int(portfolio.position.shares * scale_out_fraction))

                # avoid fully closing here; leave at least 1 share for a later true full exit
                shares = min(shares, portfolio.position.shares - 1)

                if shares > 0:
                    gross, net, fee = _sell_overlay(
                        portfolio, shares, close, strategy.transaction_cost_bps
                    )

                    portfolio.position.scale_steps = max(0, portfolio.position.scale_steps - 1)

                    trade_log.append({
                        "date": str(date.date()),
                        "action": "SELL_REDUCE_PROFIT",
                        "shares": shares,
                        "price": close,
                        "gross_pnl": round(gross, 6),
                        "net_pnl": round(net, 6),
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    })

                    action = "reduce_profit"

            if (
                strategy.risk.stop_loss_pct is not None
                and profit_pct <= -strategy.risk.stop_loss_pct
            ):
                sold = portfolio.position.shares
                gross, net, fee = _sell_overlay(
                    portfolio, sold, close, strategy.transaction_cost_bps
                )
                portfolio.last_exit_bar_index = i

                trade_log.append({
                    "date": str(date.date()),
                    "action": "SELL_ALL_STOP_LOSS",
                    "shares": sold,
                    "price": close,
                    "gross_pnl": round(gross, 6),
                    "net_pnl": round(net, 6),
                    "fee": round(fee, 6),
                    "sleeve": "overlay",
                })
                events.append({
                    "date": str(date.date()),
                    "event_type": "STOP_LOSS",
                    "details": f"Overlay sold {sold} shares",
                })
                action = "stop_loss"

            elif (
                strategy.risk.take_profit_pct is not None
                and profit_pct >= strategy.risk.take_profit_pct
            ):
                sold = portfolio.position.shares
                gross, net, fee = _sell_overlay(
                    portfolio, sold, close, strategy.transaction_cost_bps
                )
                portfolio.last_exit_bar_index = i

                trade_log.append({
                    "date": str(date.date()),
                    "action": "SELL_ALL_TAKE_PROFIT",
                    "shares": sold,
                    "price": close,
                    "gross_pnl": round(gross, 6),
                    "net_pnl": round(net, 6),
                    "fee": round(fee, 6),
                    "sleeve": "overlay",
                })
                events.append({
                    "date": str(date.date()),
                    "event_type": "TAKE_PROFIT",
                    "details": f"Overlay sold {sold} shares",
                })
                action = "take_profit"

            elif (
                strategy.risk.partial_take_profit is not None
                and portfolio.position.partial_take_profit_count
                < strategy.risk.partial_take_profit.max_triggers
                and profit_pct >= strategy.risk.partial_take_profit.trigger_profit_pct
            ):
                sold = max(
                    1,
                    int(
                        portfolio.position.shares
                        * strategy.risk.partial_take_profit.sell_fraction_of_position
                    ),
                )
                gross, net, fee = _sell_overlay(
                    portfolio, sold, close, strategy.transaction_cost_bps
                )
                portfolio.position.partial_take_profit_count += 1

                trade_log.append({
                    "date": str(date.date()),
                    "action": "SELL_PARTIAL_TAKE_PROFIT",
                    "shares": sold,
                    "price": close,
                    "gross_pnl": round(gross, 6),
                    "net_pnl": round(net, 6),
                    "fee": round(fee, 6),
                    "sleeve": "overlay",
                })
                events.append({
                    "date": str(date.date()),
                    "event_type": "PARTIAL_TAKE_PROFIT",
                    "details": f"Overlay sold {sold} shares",
                })
                action = "partial_take_profit"

        # === PARTIAL REDUCE / FULL EXIT ===
        if exit_signal and portfolio.position.in_position and action == "":

            # reduce first if position is still large enough
            if portfolio.position.shares > 1:
                shares = max(1, int(portfolio.position.shares * scale_out_fraction))

                # if this reduction would consume the whole position, do a true full exit instead
                if shares >= portfolio.position.shares:
                    shares = portfolio.position.shares

                if shares < portfolio.position.shares:
                    gross, net, fee = _sell_overlay(
                        portfolio, shares, close, strategy.transaction_cost_bps
                    )

                    portfolio.position.scale_steps = max(0, portfolio.position.scale_steps - 1)

                    trade_log.append({
                        "date": str(date.date()),
                        "action": "SELL_REDUCE",
                        "shares": shares,
                        "price": close,
                        "gross_pnl": round(gross, 6),
                        "net_pnl": round(net, 6),
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    })

                    action = "reduce"

                else:
                    gross, net, fee = _sell_overlay(
                        portfolio, shares, close, strategy.transaction_cost_bps
                    )
                    portfolio.position.scale_steps = 0
                    portfolio.last_exit_bar_index = i

                    trade_log.append({
                        "date": str(date.date()),
                        "action": "SELL_ALL",
                        "shares": shares,
                        "price": close,
                        "gross_pnl": round(gross, 6),
                        "net_pnl": round(net, 6),
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    })

                    action = "exit"

            else:
                shares = portfolio.position.shares
                gross, net, fee = _sell_overlay(
                    portfolio, shares, close, strategy.transaction_cost_bps
                )
                portfolio.position.scale_steps = 0
                portfolio.last_exit_bar_index = i

                trade_log.append({
                    "date": str(date.date()),
                    "action": "SELL_ALL",
                    "shares": shares,
                    "price": close,
                    "gross_pnl": round(gross, 6),
                    "net_pnl": round(net, 6),
                    "fee": round(fee, 6),
                    "sleeve": "overlay",
                })

                action = "exit"

        in_cooldown = (
            portfolio.last_exit_bar_index is not None
            and (i - portfolio.last_exit_bar_index) <= strategy.risk.cooldown_bars
        )

        # === SCALE-IN ENTRY ===
        if entry_signal and (not in_cooldown) and (action == ""):

            increment_pct = scale_in_fraction

            overlay_base_capital = strategy.initial_capital * (
                1.0 - strategy.core_overlay.core_allocation_pct
                if strategy.core_overlay.enabled else 1.0
            )

            max_position_value = strategy.allocation.max_position_pct * overlay_base_capital
            current_position_value = portfolio.position.shares * close
            remaining_capacity = max(0.0, max_position_value - current_position_value)

            target_increment = overlay_base_capital * increment_pct
            buy_budget = min(target_increment, remaining_capacity, portfolio.overlay_cash)

            shares = int(buy_budget // close)

            if shares > 0:
                notional = shares * close
                fee = transaction_cost(notional, strategy.transaction_cost_bps)
                total = notional + fee

                if total <= portfolio.overlay_cash:

                    existing = portfolio.position.shares
                    new_total = existing + shares

                    new_avg = (
                        ((existing * portfolio.position.avg_entry_price) + (shares * close)) / new_total
                        if new_total > 0 else 0.0
                    )

                    portfolio.overlay_cash -= total
                    portfolio.overlay_fees_paid += fee

                    portfolio.position.shares = new_total
                    portfolio.position.avg_entry_price = new_avg
                    portfolio.position.scale_steps += 1

                    trade_log.append({
                        "date": str(date.date()),
                        "action": "BUY_ADD" if existing > 0 else "BUY",
                        "shares": shares,
                        "price": close,
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    })

                    action = "scale_in"

        core_mv = portfolio.core_market_value(close)
        overlay_mv = portfolio.overlay_market_value(close)

        core_eq = portfolio.core_equity(close)
        overlay_eq = portfolio.overlay_equity(close)
        total_eq = portfolio.total_equity(close)

        current_profit_pct = (
            (close / portfolio.position.avg_entry_price - 1.0)
            if portfolio.position.in_position and portfolio.position.avg_entry_price > 0
            else 0.0
        )

        overlay_unrealized_pnl = (
            (close - portfolio.position.avg_entry_price) * portfolio.position.shares
            if portfolio.position.in_position
            else 0.0
        )

        timeline.append({
            "date": str(date.date()),
            "strategy_equity": round(total_eq, 6),
            "benchmark_equity": round(float(bench.iloc[i]), 6),
            "cash": round(portfolio.cash, 6),

            "core_cash": round(portfolio.core_cash, 6),
            "core_shares": int(portfolio.core_shares),
            "core_market_value": round(core_mv, 6),
            "core_equity": round(core_eq, 6),
            "core_fees_paid": round(portfolio.core_fees_paid, 6),

            "overlay_cash": round(portfolio.overlay_cash, 6),
            "overlay_position_shares": int(portfolio.position.shares),
            "overlay_position_market_value": round(overlay_mv, 6),
            "overlay_avg_entry_price": round(portfolio.position.avg_entry_price, 6),
            "overlay_equity": round(overlay_eq, 6),
            "overlay_realized_pnl": round(portfolio.overlay_realized_pnl, 6),
            "overlay_unrealized_pnl": round(overlay_unrealized_pnl, 6),
            "overlay_fees_paid": round(portfolio.overlay_fees_paid, 6),

            "core_pnl": round(core_eq - portfolio.core_initial_capital, 6),
            "overlay_pnl": round(overlay_eq - portfolio.overlay_initial_capital, 6),

            "core_weight_pct": round((core_eq / total_eq) * 100, 6) if total_eq else 0.0,
            "overlay_weight_pct": round((overlay_eq / total_eq) * 100, 6) if total_eq else 0.0,

            "current_profit_pct": round(current_profit_pct * 100, 6),

            "entry_signal": bool(entry_signal),
            "exit_signal": bool(exit_signal),
            "cooldown_active": bool(in_cooldown),
            "action_taken": action,
        })

    tdf = pd.DataFrame(timeline)
    trades = pd.DataFrame(trade_log)

    summary = build_summary(tdf, trades, strategy)
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
    )