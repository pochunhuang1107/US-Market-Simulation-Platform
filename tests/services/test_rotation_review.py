from __future__ import annotations

import json

from market_simulator.platform.services.rotation_review import (
    RotationReviewService,
    build_rotation_rebalance_rows,
    is_rotation_run,
)


def test_rotation_run_detection_uses_config_summary_or_timeline_fields() -> None:
    assert is_rotation_run(config={"rotation": {"enabled": True}}) is True
    assert is_rotation_run(summary={"strategy_type": "rotation"}) is True
    assert is_rotation_run(timeline_rows=[{"date": "2024-01-02", "selected_assets": "[]"}]) is True
    assert is_rotation_run(config={"rotation": {"enabled": False}}, summary={"strategy_type": "single"}) is False


def test_rotation_timeline_rows_transform_into_rebalance_rows() -> None:
    rows = build_rotation_rebalance_rows(
        [
            {
                "date": "2024-01-02",
                "rebalance": "True",
                "selected_assets": "['XLK', 'QQQ']",
                "target_weights": "{'XLK': 0.5, 'QQQ': 0.5}",
                "asset_returns": "{'XLK': 0.12, 'QQQ': 0.08, 'TLT': -0.01}",
                "asset_ranks": "{'XLK': 1, 'QQQ': 2, 'TLT': 3}",
                "cash": "123.45",
                "holdings": "{'XLK': {'shares': 10, 'market_value': 1000, 'weight_pct': 50.0}}",
            }
        ],
        [
            {
                "date": "2024-01-02",
                "action": "BUY",
                "symbol": "XLK",
                "shares": "10",
                "price": "100",
                "fee": "1.25",
            }
        ],
        universe=["XLK", "QQQ", "TLT"],
    )

    assert len(rows) == 1
    rebalance = rows[0]
    assert rebalance["date"] == "2024-01-02"
    assert rebalance["selected_assets"] == ["XLK", "QQQ"]
    assert rebalance["target_weights"] == {"XLK": 0.5, "QQQ": 0.5}
    assert rebalance["asset_ranks"][0] == {
        "symbol": "XLK",
        "rank": 1,
        "trailing_return_pct": 12.0,
        "target_weight_pct": 50.0,
        "selected": True,
    }
    assert rebalance["trades"][0]["notional"] == 1000.0
    assert rebalance["cash"] == 123.45
    assert rebalance["holdings"][0]["symbol"] == "XLK"


def test_rotation_rebalance_transform_handles_missing_optional_fields() -> None:
    rows = build_rotation_rebalance_rows(
        [{"date": "2024-01-02", "action_taken": "rebalance"}],
        [],
    )

    assert rows == [
        {
            "id": "rotation-rebalance-2024-01-02-0",
            "date": "2024-01-02",
            "selected_assets": [],
            "target_weights": {},
            "asset_ranks": [],
            "trades": [],
            "cash": None,
            "holdings": [],
            "risk_filter_passed": None,
            "fallback_used": None,
        }
    ]


def test_rotation_review_service_loads_metrics_from_artifacts(tmp_path) -> None:
    (tmp_path / "timeline.csv").write_text(
        "date,rebalance,selected_assets,target_weights,asset_returns,asset_ranks,cash,holdings\n"
        "2024-01-02,True,\"['XLK']\",\"{'XLK': 1.0}\",\"{'XLK': 0.1}\",\"{'XLK': 1}\",10,\"{'XLK': {'shares': 9, 'market_value': 990, 'weight_pct': 99}}\"\n",
        encoding="utf-8",
    )
    (tmp_path / "trade_log.csv").write_text(
        "date,action,symbol,shares,price\n2024-01-02,BUY,XLK,9,110\n",
        encoding="utf-8",
    )
    (tmp_path / "report_bundle.json").write_text(
        json.dumps(
            {
                "summary": {
                    "universe_equal_weight_buy_hold_return_pct": 8.0,
                    "alpha_vs_universe_equal_weight_pct": 2.5,
                }
            }
        ),
        encoding="utf-8",
    )

    response = RotationReviewService().load_rotation_review(
        {
            "timeline": str(tmp_path / "timeline.csv"),
            "trade_log": str(tmp_path / "trade_log.csv"),
            "report_bundle": str(tmp_path / "report_bundle.json"),
        },
        config={"rotation": {"enabled": True, "universe": ["XLK", "QQQ"]}},
        summary={
            "total_return_pct": 10.5,
            "benchmark_return_pct": 7.0,
            "max_drawdown_pct": -6.0,
        },
    )

    assert response is not None
    assert response["is_rotation"] is True
    assert response["metrics"]["strategy_return_pct"] == 10.5
    assert response["metrics"]["universe_equal_weight_return_pct"] == 8.0
    assert response["metrics"]["alpha_vs_universe_equal_weight_pct"] == 2.5
    assert response["metrics"]["universe_size"] == 2
    assert response["rebalances"][0]["trades"][0]["symbol"] == "XLK"
