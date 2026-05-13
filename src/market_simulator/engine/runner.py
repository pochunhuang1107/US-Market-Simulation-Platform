from __future__ import annotations

import pandas as pd

from market_simulator.data.model_signals import ModelSignalRepository
from market_simulator.engine.execution import transaction_cost
from market_simulator.engine.model_signal import run_model_signal_simulation
from market_simulator.engine.portfolio import PortfolioState
from market_simulator.engine.rotation import run_rotation_simulation
from market_simulator.models.strategy_v2 import AtomicRule, GroupRule, NotRule, SequenceRule, WindowRule
from market_simulator.models.result import SimulationResult
from market_simulator.reporting.metrics import (
    build_summary,
    build_sleeve_summary,
    build_yearly_report,
    build_overlay_diagnostics,
)
from market_simulator.strategy.dataframe_resolution import resolve_market_dataframe, row_position_for_date
from market_simulator.strategy.enricher import enrich_market_data
from market_simulator.strategy.evaluator import evaluate_rule
from market_simulator.settings import get_settings


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
        portfolio.position.scale_steps = 0
        portfolio.last_scale_in_bar_index = None

    return gross, net, fee


def _scale_in_allowed(
    portfolio: PortfolioState,
    *,
    index: int,
    max_scale_in_steps: int | None,
    min_bars_between_scale_ins: int,
    requires_persistent_signal: bool,
    entry_signal_streak: int,
) -> bool:
    if not portfolio.position.in_position:
        return True

    if (
        max_scale_in_steps is not None
        and portfolio.position.scale_steps >= max_scale_in_steps
    ):
        return False

    last_scale_in_bar_index = portfolio.last_scale_in_bar_index
    if last_scale_in_bar_index is None:
        return True

    bars_since_last_scale_in = index - last_scale_in_bar_index
    if bars_since_last_scale_in < min_bars_between_scale_ins:
        return False

    if requires_persistent_signal:
        required_streak = min_bars_between_scale_ins + 1
        if entry_signal_streak < required_streak:
            return False

    return True


def _collect_atomic_rules(rule, out):
    if isinstance(rule, AtomicRule):
        out.append(rule)
    elif isinstance(rule, NotRule):
        _collect_atomic_rules(rule.rule, out)
    elif isinstance(rule, WindowRule):
        _collect_atomic_rules(rule.rule, out)
    elif isinstance(rule, SequenceRule):
        for step in rule.steps:
            _collect_atomic_rules(step, out)
    elif isinstance(rule, GroupRule):
        for child in rule.rules:
            _collect_atomic_rules(child, out)


def _safe_timeline_value(row, column: str):
    if column not in row:
        return None
    value = row[column]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 6)
    return value


def _rule_symbol(rule: AtomicRule, strategy) -> str:
    return (rule.symbol or strategy.tradable_symbol or "").upper()


def _status_from_comparison(actual, operator: str | None, threshold) -> str:
    if actual is None or threshold is None or operator not in {"below", "above"}:
        return "unavailable"
    try:
        actual_float = float(actual)
        threshold_float = float(threshold)
    except (TypeError, ValueError):
        return "unavailable"

    matched = actual_float < threshold_float if operator == "below" else actual_float > threshold_float
    return "matched" if matched else "not_matched"


def _rule_text(operator: str | None, threshold) -> str | None:
    if operator is None or threshold is None:
        return None
    symbol = "<" if operator == "below" else ">" if operator == "above" else operator
    return f"{symbol} {threshold}"


def _rule_source_label(source: str) -> str:
    if source == "entry_rule":
        return "entry_rule"
    if source == "exit_rule":
        return "exit_rule"
    return source


def _side_for_trade_action(action: str) -> str:
    upper = action.upper()
    if upper.startswith("BUY"):
        return "BUY"
    if upper.startswith("SELL"):
        return "SELL"
    return action


def _round_capital_value(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _minimum_trade_rejection_reason(
    pm,
    *,
    shares: int,
    price: float,
    total_equity: float,
) -> str | None:
    if pm is None:
        return None

    notional = shares * price

    minimum_trade_shares = getattr(pm, "minimum_trade_shares", None)
    if minimum_trade_shares is not None and shares < minimum_trade_shares:
        return "minimum_trade_shares"

    minimum_trade_notional = getattr(pm, "minimum_trade_notional", None)
    if minimum_trade_notional is not None and notional < minimum_trade_notional:
        return "minimum_trade_notional"

    minimum_trade_pct_of_equity = getattr(pm, "minimum_trade_pct_of_equity", None)
    if (
        minimum_trade_pct_of_equity is not None
        and total_equity > 0
        and (notional / total_equity) < minimum_trade_pct_of_equity
    ):
        return "minimum_trade_pct_of_equity"

    return None


def _overlay_capital_state(portfolio: PortfolioState, close: float) -> dict:
    position_value = portfolio.overlay_market_value(close)
    equity = portfolio.overlay_equity(close)
    return {
        "equity": equity,
        "cash": portfolio.overlay_cash,
        "position_shares": portfolio.position.shares,
        "position_value": position_value,
        "position_allocation_pct": (position_value / equity) * 100 if equity else 0.0,
    }


def _buy_capital_context(
    before: dict,
    portfolio: PortfolioState,
    close: float,
    shares: int,
    fee: float,
    max_position_value: float,
) -> dict:
    after = _overlay_capital_state(portfolio, close)
    trade_notional = shares * close
    remaining_capacity_after = max(0.0, max_position_value - after["position_value"])
    return {
        "trade_notional": _round_capital_value(trade_notional),
        "trade_fee": _round_capital_value(fee),
        "trade_total_cost": _round_capital_value(trade_notional + fee),
        "equity_before_trade": _round_capital_value(before["equity"]),
        "equity_after_trade": _round_capital_value(after["equity"]),
        "cash_before_trade": _round_capital_value(before["cash"]),
        "cash_after_trade": _round_capital_value(after["cash"]),
        "position_shares_before": int(before["position_shares"]),
        "position_shares_after": int(after["position_shares"]),
        "position_value_after": _round_capital_value(after["position_value"]),
        "position_allocation_pct_after": _round_capital_value(after["position_allocation_pct"]),
        "remaining_capacity_after": _round_capital_value(remaining_capacity_after),
        "max_position_value": _round_capital_value(max_position_value),
    }


def _sell_capital_context(
    before: dict,
    portfolio: PortfolioState,
    close: float,
    shares: int,
    fee: float,
    gross_pnl: float,
    net_pnl: float,
) -> dict:
    after = _overlay_capital_state(portfolio, close)
    return {
        "trade_notional": _round_capital_value(shares * close),
        "trade_fee": _round_capital_value(fee),
        "gross_pnl": _round_capital_value(gross_pnl),
        "net_pnl": _round_capital_value(net_pnl),
        "equity_before_trade": _round_capital_value(before["equity"]),
        "equity_after_trade": _round_capital_value(after["equity"]),
        "cash_after_trade": _round_capital_value(after["cash"]),
        "position_shares_before": int(before["position_shares"]),
        "position_shares_after": int(after["position_shares"]),
        "position_value_after": _round_capital_value(after["position_value"]),
        "position_allocation_pct_after": _round_capital_value(after["position_allocation_pct"]),
    }


def _signal_column_values(rule: AtomicRule, row, symbol: str) -> dict[str, object]:
    values: dict[str, object] = {}

    if rule.type in {"rsi_below", "rsi_above"}:
        column = f"rsi_{rule.lookback}"
        value = _safe_timeline_value(row, column)
        values[f"{symbol}_RSI_{rule.lookback}"] = value
    elif rule.type in {"series_below", "series_above"}:
        value = _safe_timeline_value(row, "value")
        if value is None:
            value = _safe_timeline_value(row, "close")
        values[f"{symbol}_value"] = value
    elif rule.type in {"sma_cross_above", "sma_cross_below", "sma_above"}:
        for window in (rule.fast_window, rule.slow_window):
            column = f"sma_{window}"
            value = _safe_timeline_value(row, column)
            values[f"{symbol}_SMA_{window}"] = value
    elif rule.type in {"macd_bullish_cross", "macd_bearish_cross"}:
        for source_column, output_column in (
            ("macd", f"{symbol}_MACD"),
            ("macd_signal", f"{symbol}_MACD_signal"),
        ):
            value = _safe_timeline_value(row, source_column)
            values[output_column] = value
    elif rule.type in {"kd_golden_cross", "kd_dead_cross"}:
        for source_column, output_column in (
            ("k", f"{symbol}_KD_K"),
            ("d", f"{symbol}_KD_D"),
        ):
            value = _safe_timeline_value(row, source_column)
            values[output_column] = value
    elif rule.type in {"realized_volatility_below", "realized_volatility_above"}:
        column = f"realized_volatility_{rule.lookback}"
        value = _safe_timeline_value(row, column)
        values[f"{symbol}_realized_volatility_{rule.lookback}"] = value

    return values


def _timeline_rule_values(bundle, strategy, index: int) -> dict:
    values: dict = {}
    current_date = pd.Timestamp(bundle.tradable.iloc[index]["date"])
    trade_row = bundle.tradable.iloc[index]

    close_value = _safe_timeline_value(trade_row, "close")
    if close_value is not None:
        values["close"] = close_value

    rules = []
    _collect_atomic_rules(strategy.entry_rule, rules)
    _collect_atomic_rules(strategy.exit_rule, rules)

    for rule in rules:
        try:
            target_df = resolve_market_dataframe(bundle, rule.symbol, strategy.tradable_symbol)
        except ValueError:
            continue
        row_pos = row_position_for_date(target_df, current_date)
        if row_pos is None:
            continue
        row = target_df.iloc[row_pos]
        values.update(_signal_column_values(rule, row, _rule_symbol(rule, strategy)))

    return values


def _signal_for_rule(rule: AtomicRule, bundle, strategy, index: int, source: str) -> dict | None:
    current_date = pd.Timestamp(bundle.tradable.iloc[index]["date"])
    symbol = _rule_symbol(rule, strategy)
    try:
        target_df = resolve_market_dataframe(bundle, rule.symbol, strategy.tradable_symbol)
    except ValueError:
        return None

    row_pos = row_position_for_date(target_df, current_date)
    if row_pos is None:
        return None
    row = target_df.iloc[row_pos]

    operator: str | None = None
    threshold = rule.threshold
    actual_value = None
    label = None

    if rule.type in {"rsi_below", "rsi_above"}:
        operator = "below" if rule.type == "rsi_below" else "above"
        actual_value = _safe_timeline_value(row, f"rsi_{rule.lookback}")
        label = f"{symbol} RSI({rule.lookback})"
    elif rule.type in {"series_below", "series_above"}:
        operator = "below" if rule.type == "series_below" else "above"
        actual_value = _safe_timeline_value(row, "value")
        if actual_value is None:
            actual_value = _safe_timeline_value(row, "close")
        label = symbol or str(rule.symbol or "Series").upper()
    elif rule.type in {"realized_volatility_below", "realized_volatility_above"}:
        operator = "below" if rule.type == "realized_volatility_below" else "above"
        actual_value = _safe_timeline_value(row, f"realized_volatility_{rule.lookback}")
        label = f"{symbol} realized volatility({rule.lookback})"
    elif rule.type in {"sma_above", "sma_cross_above", "sma_cross_below"}:
        operator = "above" if rule.type.endswith("above") else "below"
        actual_value = _safe_timeline_value(row, f"sma_{rule.fast_window}")
        threshold = _safe_timeline_value(row, f"sma_{rule.slow_window}")
        label = f"{symbol} SMA({rule.fast_window})"
    elif rule.type in {"macd_bullish_cross", "macd_bearish_cross"}:
        operator = "above" if rule.type == "macd_bullish_cross" else "below"
        actual_value = _safe_timeline_value(row, "macd")
        threshold = _safe_timeline_value(row, "macd_signal")
        label = f"{symbol} MACD"
    elif rule.type in {"kd_golden_cross", "kd_dead_cross"}:
        operator = "above" if rule.type == "kd_golden_cross" else "below"
        actual_value = _safe_timeline_value(row, "k")
        threshold = _safe_timeline_value(row, "d")
        label = f"{symbol} KD/stochastic"
    else:
        return None

    status = _status_from_comparison(actual_value, operator, threshold)
    return {
        "label": label,
        "actual": actual_value,
        "actual_value": actual_value,
        "rule": _rule_text(operator, threshold),
        "operator": operator,
        "threshold": threshold,
        "status": status,
        "source": _rule_source_label(source),
    }


def _signals_for_rules(rule_node, bundle, strategy, index: int, source: str) -> list[dict]:
    rules = []
    _collect_atomic_rules(rule_node, rules)
    signals = []
    for rule in rules:
        signal = _signal_for_rule(rule, bundle, strategy, index, source)
        if signal is not None:
            signals.append(signal)
    return signals


def _risk_signal(
    label: str,
    actual_value,
    operator: str,
    threshold,
    source: str,
    *,
    status: str | None = None,
) -> dict:
    return {
        "label": label,
        "actual": actual_value,
        "actual_value": actual_value,
        "rule": _rule_text(operator, threshold),
        "operator": operator,
        "threshold": threshold,
        "status": status or _status_from_comparison(actual_value, operator, threshold),
        "source": source,
    }


def run_simulation(bundle, strategy, model_signal_frame: pd.DataFrame | None = None):
    if getattr(getattr(strategy, "rotation", None), "enabled", False):
        return run_rotation_simulation(bundle, strategy)
    if getattr(getattr(strategy, "model_signal", None), "enabled", False):
        if model_signal_frame is None:
            settings = get_settings()
            if not settings.model_signal_data_path.strip():
                raise ValueError(
                    "model_signal strategy execution requires a precomputed "
                    "model_signal_frame or MODEL_SIGNAL_DATA_PATH"
                )
            model_signal = strategy.model_signal
            model_signal_frame = ModelSignalRepository(
                settings.model_signal_data_path,
                supported_symbols=settings.supported_etf_symbols,
                duckdb_database=settings.duckdb_database,
                s3_region=settings.s3_region,
            ).load(
                model_version=model_signal.model_version,
                universe=model_signal.universe,
                start_date=strategy.start_date,
                end_date=strategy.end_date,
            )
        return run_model_signal_simulation(bundle, strategy, model_signal_frame)

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
    trade_signal_snapshots = []
    entry_signal_streak = 0

    def record_trade(
        trade: dict,
        signals: list[dict],
        capital_context: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        event_index = len(trade_log)
        trade_log.append(trade)
        trade_date = str(trade.get("date") or "")
        trade_action = str(trade.get("action") or "TRADE")
        snapshot = {
            "id": f"{trade_date or 'trade'}-{event_index}",
            "event_index": event_index,
            "date": trade_date,
            "action": trade_action,
            "side": _side_for_trade_action(trade_action),
            "price": trade.get("price"),
            "shares": trade.get("shares"),
            "signals": signals,
        }
        if capital_context:
            snapshot["capital_context"] = capital_context
        if metadata:
            snapshot.update(metadata)
        trade_signal_snapshots.append(snapshot)

    for i, row in df.iterrows():
        date = pd.Timestamp(row["date"])
        close = float(row["close"])

        entry_signal = evaluate_rule(strategy.entry_rule, bundle, i, strategy.tradable_symbol)
        exit_signal = evaluate_rule(strategy.exit_rule, bundle, i, strategy.tradable_symbol)
        entry_signal_streak = entry_signal_streak + 1 if entry_signal else 0
        action = ""
        minimum_trade_skip_reason = None

        # === POSITION MANAGEMENT CONFIG (NEW) ===
        pm = getattr(strategy, "position_management", None)

        pm_fields_set = getattr(pm, "model_fields_set", set()) if pm else set()
        scale_management_fields = {
            "scale_in_fraction",
            "scale_out_fraction",
            "exit_behavior",
            "profit_reduce_threshold",
            "max_scale_in_steps",
            "min_bars_between_scale_ins",
            "scale_in_requires_persistent_signal",
        }
        position_management_enabled = pm is not None and (
            not pm_fields_set or bool(pm_fields_set & scale_management_fields)
        )
        scale_in_fraction = pm.scale_in_fraction if position_management_enabled else 1.0
        scale_out_fraction = (pm.scale_out_fraction or 0.5) if position_management_enabled else 1.0
        exit_behavior = pm.exit_behavior if position_management_enabled else "sell_all"
        profit_reduce_threshold = pm.profit_reduce_threshold if position_management_enabled else None
        max_scale_in_steps = pm.max_scale_in_steps if position_management_enabled else None
        min_bars_between_scale_ins = pm.min_bars_between_scale_ins if position_management_enabled else 0
        scale_in_requires_persistent_signal = (
            pm.scale_in_requires_persistent_signal if position_management_enabled else False
        )
        total_equity_before_trade = portfolio.total_equity(close)

        # risk / exits for overlay sleeve only
        if portfolio.position.in_position and action == "":
            # === EARLY PROFIT REDUCE (NEW) ===
            profit_pct = close / portfolio.position.avg_entry_price - 1.0

            if (
                position_management_enabled
                and profit_reduce_threshold is not None
                and profit_pct > profit_reduce_threshold
                and action == ""
                and portfolio.position.shares > 1
            ):
                shares = max(1, int(portfolio.position.shares * scale_out_fraction))

                # avoid fully closing here; leave at least 1 share for a later true full exit
                shares = min(shares, portfolio.position.shares - 1)

                minimum_trade_skip_reason = _minimum_trade_rejection_reason(
                    pm,
                    shares=shares,
                    price=close,
                    total_equity=total_equity_before_trade,
                )

                if shares > 0 and minimum_trade_skip_reason is None:
                    capital_before = _overlay_capital_state(portfolio, close)
                    gross, net, fee = _sell_overlay(
                        portfolio, shares, close, strategy.transaction_cost_bps
                    )
                    capital_context = _sell_capital_context(
                        capital_before, portfolio, close, shares, fee, gross, net
                    )

                    portfolio.position.scale_steps = max(0, portfolio.position.scale_steps - 1)

                    record_trade(
                        {
                            "date": str(date.date()),
                            "action": "SELL_REDUCE_PROFIT",
                            "shares": shares,
                            "price": close,
                            "gross_pnl": round(gross, 6),
                            "net_pnl": round(net, 6),
                            "fee": round(fee, 6),
                            "sleeve": "overlay",
                        },
                        [
                            _risk_signal(
                                "Current profit %",
                                round(profit_pct * 100, 6),
                                "above",
                                round(profit_reduce_threshold * 100, 6),
                                "position_management",
                                status="matched",
                            )
                        ],
                        capital_context,
                    )

                    action = "reduce_profit"
                elif shares > 0:
                    action = "skipped_min_trade"

            if (
                strategy.risk.stop_loss_pct is not None
                and profit_pct <= -strategy.risk.stop_loss_pct
            ):
                sold = portfolio.position.shares
                capital_before = _overlay_capital_state(portfolio, close)
                gross, net, fee = _sell_overlay(
                    portfolio, sold, close, strategy.transaction_cost_bps
                )
                capital_context = _sell_capital_context(
                    capital_before, portfolio, close, sold, fee, gross, net
                )
                portfolio.last_exit_bar_index = i

                record_trade(
                    {
                        "date": str(date.date()),
                        "action": "SELL_ALL_STOP_LOSS",
                        "shares": sold,
                        "price": close,
                        "gross_pnl": round(gross, 6),
                        "net_pnl": round(net, 6),
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    },
                    [
                        _risk_signal(
                            "Current profit %",
                            round(profit_pct * 100, 6),
                            "below",
                            round(-strategy.risk.stop_loss_pct * 100, 6),
                            "risk",
                            status="matched",
                        )
                    ],
                    capital_context,
                )
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
                capital_before = _overlay_capital_state(portfolio, close)
                gross, net, fee = _sell_overlay(
                    portfolio, sold, close, strategy.transaction_cost_bps
                )
                capital_context = _sell_capital_context(
                    capital_before, portfolio, close, sold, fee, gross, net
                )
                portfolio.last_exit_bar_index = i

                record_trade(
                    {
                        "date": str(date.date()),
                        "action": "SELL_ALL_TAKE_PROFIT",
                        "shares": sold,
                        "price": close,
                        "gross_pnl": round(gross, 6),
                        "net_pnl": round(net, 6),
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    },
                    [
                        _risk_signal(
                            "Current profit %",
                            round(profit_pct * 100, 6),
                            "above",
                            round(strategy.risk.take_profit_pct * 100, 6),
                            "risk",
                            status="matched",
                        )
                    ],
                    capital_context,
                )
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
                minimum_trade_skip_reason = _minimum_trade_rejection_reason(
                    pm,
                    shares=sold,
                    price=close,
                    total_equity=total_equity_before_trade,
                )
                if minimum_trade_skip_reason is None:
                    capital_before = _overlay_capital_state(portfolio, close)
                    gross, net, fee = _sell_overlay(
                        portfolio, sold, close, strategy.transaction_cost_bps
                    )
                    capital_context = _sell_capital_context(
                        capital_before, portfolio, close, sold, fee, gross, net
                    )
                    portfolio.position.partial_take_profit_count += 1

                    record_trade(
                        {
                            "date": str(date.date()),
                            "action": "SELL_PARTIAL_TAKE_PROFIT",
                            "shares": sold,
                            "price": close,
                            "gross_pnl": round(gross, 6),
                            "net_pnl": round(net, 6),
                            "fee": round(fee, 6),
                            "sleeve": "overlay",
                        },
                        [
                            _risk_signal(
                                "Current profit %",
                                round(profit_pct * 100, 6),
                                "above",
                                round(strategy.risk.partial_take_profit.trigger_profit_pct * 100, 6),
                                "risk",
                                status="matched",
                            )
                        ],
                        capital_context,
                    )
                    events.append({
                        "date": str(date.date()),
                        "event_type": "PARTIAL_TAKE_PROFIT",
                        "details": f"Overlay sold {sold} shares",
                    })
                    action = "partial_take_profit"
                else:
                    action = "skipped_min_trade"

        # === PARTIAL REDUCE / FULL EXIT ===
        if exit_signal and portfolio.position.in_position and action == "":
            if exit_behavior == "sell_all":
                shares = portfolio.position.shares
                capital_before = _overlay_capital_state(portfolio, close)
                gross, net, fee = _sell_overlay(
                    portfolio, shares, close, strategy.transaction_cost_bps
                )
                capital_context = _sell_capital_context(
                    capital_before, portfolio, close, shares, fee, gross, net
                )
                portfolio.last_exit_bar_index = i

                record_trade(
                    {
                        "date": str(date.date()),
                        "action": "SELL_ALL",
                        "shares": shares,
                        "price": close,
                        "gross_pnl": round(gross, 6),
                        "net_pnl": round(net, 6),
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    },
                    _signals_for_rules(
                        strategy.exit_rule,
                        bundle,
                        strategy,
                        i,
                        "exit_rule",
                    ),
                    capital_context,
                )

                action = "exit"

            # reduce first if position is still large enough
            elif portfolio.position.shares > 1:
                shares = max(1, int(portfolio.position.shares * scale_out_fraction))

                # if this reduction would consume the whole position, do a true full exit instead
                if shares >= portfolio.position.shares:
                    shares = portfolio.position.shares

                minimum_trade_skip_reason = _minimum_trade_rejection_reason(
                    pm,
                    shares=shares,
                    price=close,
                    total_equity=total_equity_before_trade,
                )

                if shares < portfolio.position.shares and minimum_trade_skip_reason is None:
                    capital_before = _overlay_capital_state(portfolio, close)
                    gross, net, fee = _sell_overlay(
                        portfolio, shares, close, strategy.transaction_cost_bps
                    )
                    capital_context = _sell_capital_context(
                        capital_before, portfolio, close, shares, fee, gross, net
                    )

                    portfolio.position.scale_steps = max(0, portfolio.position.scale_steps - 1)

                    record_trade(
                        {
                            "date": str(date.date()),
                            "action": "SELL_REDUCE",
                            "shares": shares,
                            "price": close,
                            "gross_pnl": round(gross, 6),
                            "net_pnl": round(net, 6),
                            "fee": round(fee, 6),
                            "sleeve": "overlay",
                        },
                        _signals_for_rules(
                            strategy.exit_rule,
                            bundle,
                            strategy,
                            i,
                            "exit_rule",
                        ),
                        capital_context,
                    )

                    action = "reduce"

                else:
                    if minimum_trade_skip_reason is not None:
                        shares = portfolio.position.shares
                        minimum_trade_skip_reason = None
                    capital_before = _overlay_capital_state(portfolio, close)
                    gross, net, fee = _sell_overlay(
                        portfolio, shares, close, strategy.transaction_cost_bps
                    )
                    capital_context = _sell_capital_context(
                        capital_before, portfolio, close, shares, fee, gross, net
                    )
                    portfolio.position.scale_steps = 0
                    portfolio.last_exit_bar_index = i

                    record_trade(
                        {
                            "date": str(date.date()),
                            "action": "SELL_ALL",
                            "shares": shares,
                            "price": close,
                            "gross_pnl": round(gross, 6),
                            "net_pnl": round(net, 6),
                            "fee": round(fee, 6),
                            "sleeve": "overlay",
                        },
                        _signals_for_rules(
                            strategy.exit_rule,
                            bundle,
                            strategy,
                            i,
                            "exit_rule",
                        ),
                        capital_context,
                    )

                    action = "exit"

            else:
                shares = portfolio.position.shares
                capital_before = _overlay_capital_state(portfolio, close)
                gross, net, fee = _sell_overlay(
                    portfolio, shares, close, strategy.transaction_cost_bps
                )
                capital_context = _sell_capital_context(
                    capital_before, portfolio, close, shares, fee, gross, net
                )
                portfolio.position.scale_steps = 0
                portfolio.last_exit_bar_index = i

                record_trade(
                    {
                        "date": str(date.date()),
                        "action": "SELL_ALL",
                        "shares": shares,
                        "price": close,
                        "gross_pnl": round(gross, 6),
                        "net_pnl": round(net, 6),
                        "fee": round(fee, 6),
                        "sleeve": "overlay",
                    },
                    _signals_for_rules(
                        strategy.exit_rule,
                        bundle,
                        strategy,
                        i,
                        "exit_rule",
                    ),
                    capital_context,
                )

                action = "exit"

        in_cooldown = (
            portfolio.last_exit_bar_index is not None
            and (i - portfolio.last_exit_bar_index) <= strategy.risk.cooldown_bars
        )

        # === ENTRY ===
        if entry_signal and (not in_cooldown) and (action == ""):
            can_scale_in = _scale_in_allowed(
                portfolio,
                index=i,
                max_scale_in_steps=max_scale_in_steps,
                min_bars_between_scale_ins=min_bars_between_scale_ins,
                requires_persistent_signal=scale_in_requires_persistent_signal,
                entry_signal_streak=entry_signal_streak,
            )

            increment_pct = (
                scale_in_fraction
                if position_management_enabled
                else strategy.allocation.entry_value
            )

            overlay_base_capital = strategy.initial_capital * (
                1.0 - strategy.core_overlay.core_allocation_pct
                if strategy.core_overlay.enabled else 1.0
            )

            max_position_value = strategy.allocation.max_position_pct * overlay_base_capital
            current_position_value = portfolio.position.shares * close
            remaining_capacity = max(0.0, max_position_value - current_position_value)

            target_increment = overlay_base_capital * increment_pct
            buy_budget = (
                min(target_increment, remaining_capacity, portfolio.overlay_cash)
                if can_scale_in
                else 0.0
            )

            shares = int(buy_budget // close)

            if shares > 0:
                notional = shares * close
                minimum_trade_skip_reason = _minimum_trade_rejection_reason(
                    pm,
                    shares=shares,
                    price=close,
                    total_equity=total_equity_before_trade,
                )
                fee = transaction_cost(notional, strategy.transaction_cost_bps)
                total = notional + fee

                if total <= portfolio.overlay_cash and minimum_trade_skip_reason is None:

                    existing = portfolio.position.shares
                    bars_since_last_scale_in = (
                        None
                        if portfolio.last_scale_in_bar_index is None
                        else i - portfolio.last_scale_in_bar_index
                    )
                    capital_before = _overlay_capital_state(portfolio, close)
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
                    portfolio.last_scale_in_bar_index = i
                    capital_context = _buy_capital_context(
                        capital_before,
                        portfolio,
                        close,
                        shares,
                        fee,
                        max_position_value,
                    )

                    record_trade(
                        {
                            "date": str(date.date()),
                            "action": "BUY_ADD" if existing > 0 else "BUY",
                            "shares": shares,
                            "price": close,
                            "fee": round(fee, 6),
                            "sleeve": "overlay",
                        },
                        _signals_for_rules(
                            strategy.entry_rule,
                            bundle,
                            strategy,
                            i,
                            "entry_rule",
                        ),
                        capital_context,
                        {
                            "scale_step_after": portfolio.position.scale_steps,
                            "max_scale_in_steps": max_scale_in_steps,
                            "bars_since_last_scale_in": bars_since_last_scale_in,
                        } if position_management_enabled else None,
                    )

                    action = "scale_in"
                elif minimum_trade_skip_reason is not None:
                    action = "skipped_min_trade"

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
            "minimum_trade_skip_reason": minimum_trade_skip_reason,
            **_timeline_rule_values(bundle, strategy, i),
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
        trade_signal_snapshots=trade_signal_snapshots,
    )
