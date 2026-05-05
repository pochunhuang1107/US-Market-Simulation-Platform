from __future__ import annotations

import json

from market_simulator.platform.services.trade_event_inspector import TradeEventInspectorService


def _rsi_config() -> dict:
    return {
        "tradable_symbol": "QQQ",
        "entry_rule": {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 35,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 70,
        },
    }


def test_trade_event_inspector_prefers_signal_snapshot_artifact(tmp_path) -> None:
    (tmp_path / "trade_log.csv").write_text(
        "date,action,shares,price\n2024-01-15,BUY,100,90\n",
        encoding="utf-8",
    )
    (tmp_path / "timeline.csv").write_text(
        "date,entry_signal,exit_signal,QQQ_RSI_14\n2024-01-15,True,False,99\n",
        encoding="utf-8",
    )
    (tmp_path / "trade_signal_snapshots.json").write_text(
        json.dumps(
            [
                {
                    "event_index": 0,
                    "date": "2024-01-15",
                    "action": "BUY",
                    "side": "BUY",
                    "price": 90,
                    "shares": 100,
                    "capital_context": {
                        "trade_notional": 9000,
                        "equity_before_trade": 10000,
                        "cash_after_trade": 1000,
                        "position_shares_after": 100,
                        "position_value_after": 9000,
                        "position_allocation_pct_after": 90,
                    },
                    "signals": [
                        {
                            "label": "QQQ RSI(14)",
                            "actual": 28.5,
                            "operator": "below",
                            "threshold": 35,
                            "status": "matched",
                            "source": "entry_rule",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    response = TradeEventInspectorService().load_trade_events(
        {
            "trade_log": str(tmp_path / "trade_log.csv"),
            "timeline": str(tmp_path / "timeline.csv"),
            "trade_signal_snapshots": str(tmp_path / "trade_signal_snapshots.json"),
        },
        config=_rsi_config(),
    )

    context = response["events"][0]["rule_context"][0]
    assert context["label"] == "QQQ RSI(14)"
    assert context["actual_value"] == 28.5
    assert context["threshold"] == 35.0
    assert context["result"] == "matched"
    assert context["source"] == "entry_rule"
    capital_context = response["events"][0]["capital_context"]
    assert capital_context["trade_notional"] == 9000.0
    assert capital_context["position_allocation_pct_after"] == 90.0
    assert capital_context["position_shares_after"] == 100


def test_trade_event_inspector_falls_back_to_timeline_inference_without_snapshot(tmp_path) -> None:
    (tmp_path / "trade_log.csv").write_text(
        "date,action,shares,price\n2024-01-15,BUY,100,90\n",
        encoding="utf-8",
    )
    (tmp_path / "timeline.csv").write_text(
        "date,entry_signal,exit_signal,QQQ_RSI_14\n2024-01-15,True,False,28.5\n",
        encoding="utf-8",
    )

    response = TradeEventInspectorService().load_trade_events(
        {
            "trade_log": str(tmp_path / "trade_log.csv"),
            "timeline": str(tmp_path / "timeline.csv"),
        },
        config=_rsi_config(),
    )

    context = response["events"][0]["rule_context"][0]
    assert context["label"] == "QQQ RSI(14)"
    assert context["actual_value"] == 28.5
    assert context["threshold"] == 35
    assert context["result"] == "matched"
    assert response["events"][0]["capital_context"] is None


def test_trade_event_inspector_accepts_old_snapshot_without_capital_context(tmp_path) -> None:
    (tmp_path / "trade_log.csv").write_text(
        "date,action,shares,price\n2024-01-15,BUY,100,90\n",
        encoding="utf-8",
    )
    (tmp_path / "timeline.csv").write_text(
        "date,entry_signal,exit_signal,QQQ_RSI_14\n2024-01-15,True,False,28.5\n",
        encoding="utf-8",
    )
    (tmp_path / "trade_signal_snapshots.json").write_text(
        json.dumps(
            [
                {
                    "event_index": 0,
                    "date": "2024-01-15",
                    "action": "BUY",
                    "side": "BUY",
                    "price": 90,
                    "shares": 100,
                    "signals": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    response = TradeEventInspectorService().load_trade_events(
        {
            "trade_log": str(tmp_path / "trade_log.csv"),
            "timeline": str(tmp_path / "timeline.csv"),
            "trade_signal_snapshots": str(tmp_path / "trade_signal_snapshots.json"),
        },
        config=_rsi_config(),
    )

    assert response["events"][0]["capital_context"] is None
