from __future__ import annotations

import math

import pandas as pd
import pytest

import market_simulator.services.strategy_builder_parsers as builder_parsers
from market_simulator.data.repository import MarketDataBundle, MarketDataRepository
from market_simulator.db.enums import RunStatus
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.artifact_store import LocalArtifactStore
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import get_run


@pytest.fixture(autouse=True)
def product_loop_user(create_user, current_user_ctx):
    create_user(
        user_id=current_user_ctx["id"],
        email="product-loop@example.com",
    )


@pytest.fixture(autouse=True)
def deterministic_builder_metadata(monkeypatch):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)


def _synthetic_etf_bars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    dates = pd.bdate_range(start_date, end_date)
    if len(dates) < 40:
        dates = pd.bdate_range(start_date, periods=40)

    closes = []
    for index in range(len(dates)):
        if index < 22:
            close = 120.0 - index * 1.2
        elif index < 45:
            close = 93.6 + (index - 22) * 1.4
        else:
            close = 125.8 + math.sin(index / 3) * 2.0
        closes.append(round(close, 4))

    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": [price * 0.995 for price in closes],
            "high": [price * 1.01 for price in closes],
            "low": [price * 0.99 for price in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(dates),
            "vwap": closes,
            "transactions": [10_000.0] * len(dates),
        }
    )


def _synthetic_vix(start_date: str, end_date: str) -> pd.DataFrame:
    dates = pd.bdate_range(start_date, end_date)
    if len(dates) < 40:
        dates = pd.bdate_range(start_date, periods=40)

    values = [30.0 if index < 10 else 20.0 for index in range(len(dates))]
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "VIX",
            "value": values,
            "unit": "index",
            "source": "synthetic-test",
            "series_type": "volatility_index",
            "close": values,
        }
    )


def _patch_synthetic_market_data(monkeypatch):
    def fake_get_market_data(
        self,
        tradable_symbol: str,
        reference_symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> MarketDataBundle:
        references = {}
        for symbol in reference_symbols:
            if symbol == "VIX":
                references[symbol] = _synthetic_vix(start_date, end_date)
            else:
                references[symbol] = _synthetic_etf_bars(symbol, start_date, end_date)
        return MarketDataBundle(
            tradable=_synthetic_etf_bars(tradable_symbol, start_date, end_date),
            references=references,
        )

    monkeypatch.setattr(MarketDataRepository, "get_market_data", fake_get_market_data)


def _generate_config(client, prompt: str) -> dict:
    response = client.post("/strategy-builder/generate", json={"prompt": prompt})
    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    assert isinstance(body["config"], dict)
    StrategyV2.model_validate(body["config"])
    return body["config"]


def _create_execute_and_load_run(
    *,
    client,
    db_session,
    tmp_path,
    config: dict,
    request_payload: dict | None = None,
) -> tuple[str, dict]:
    create_response = client.post(
        "/runs",
        json={
            "draft_config": config,
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": request_payload or {"source": "strategy_chat_smoke"},
            "max_attempts": 1,
        },
    )
    assert create_response.status_code == 200
    run_id = create_response.json()["id"]

    enqueue_response = client.post(f"/runs/{run_id}/enqueue")
    assert enqueue_response.status_code == 200
    assert enqueue_response.json()["status"] == "QUEUED"

    worker = RunWorkerService(
        artifact_store=LocalArtifactStore(base_dir=str(tmp_path / "artifacts"))
    )
    worker_result = worker.claim_and_execute_next_run(
        db_session,
        worker_id="product-loop-smoke-worker",
        lease_seconds=300,
    )
    assert worker_result is not None
    assert worker_result["status"] == "SUCCEEDED"

    run = get_run(db_session, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.strategy_id is None
    assert run.strategy_version_id is None
    assert run.summary_json
    assert isinstance(run.summary_json["total_return_pct"], float)
    assert run.artifact_manifest_json
    assert {"summary", "timeline", "monthly_returns", "trade_log"}.issubset(
        run.artifact_manifest_json
    )

    dashboard_response = client.get(f"/runs/{run_id}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["run"]["status"] == "SUCCEEDED"
    assert dashboard["run"]["summary_json"]["total_return_pct"] == run.summary_json["total_return_pct"]
    assert dashboard["run"]["artifact_manifest_json"]["summary"].endswith("summary.json")
    assert dashboard["chart_data"]["equity_curve"]

    return run_id, dashboard


def _save_run_and_assert_strategy_dashboard(
    *,
    client,
    run_id: str,
    name: str,
) -> dict:
    save_response = client.post(
        f"/runs/{run_id}/save-strategy",
        json={
            "name": name,
            "description": "Saved by product loop smoke test",
            "strategy_type": "SIMULATION",
        },
    )
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["run_id"] == run_id

    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    run_body = run_response.json()
    assert run_body["strategy_id"] == saved["strategy_id"]
    assert run_body["strategy_version_id"] == saved["version_id"]
    assert run_body["strategy_name"] == name

    strategy_response = client.get(f"/strategies/{saved['strategy_id']}/dashboard")
    assert strategy_response.status_code == 200
    dashboard = strategy_response.json()
    assert dashboard["strategy"]["id"] == saved["strategy_id"]
    assert dashboard["strategy"]["current_version_id"] == saved["version_id"]
    assert dashboard["versions"][0]["id"] == saved["version_id"]
    assert dashboard["versions"][0]["reference_run_id"] == run_id
    assert dashboard["versions"][0]["reference_performance"]["run_id"] == run_id
    assert dashboard["reference_run_id"] == run_id
    assert dashboard["reference_performance"]["run_id"] == run_id
    assert dashboard["associated_runs"][0]["run_id"] == run_id
    assert dashboard["associated_runs"][0]["has_artifacts"] is True
    return saved


def test_strategy_chat_draft_run_save_strategy_product_loop_smoke(
    client,
    db_session,
    monkeypatch,
    tmp_path,
    current_user_ctx,
    create_user,
):
    _patch_synthetic_market_data(monkeypatch)

    config = _generate_config(
        client,
        (
            "Create a QQQ mean reversion strategy from 2021-01-04 to 2021-04-30 "
            "with RSI below 35 and exit when RSI is above 65."
        ),
    )
    assert config["tradable_symbol"] == "QQQ"
    assert config["entry_rule"]["type"] == "rsi_below"

    run_id, _ = _create_execute_and_load_run(
        client=client,
        db_session=db_session,
        tmp_path=tmp_path,
        config=config,
    )
    saved = _save_run_and_assert_strategy_dashboard(
        client=client,
        run_id=run_id,
        name="QQQ Product Loop Smoke",
    )

    other_user = create_user(email="product-loop-other@example.com")
    current_user_ctx["id"] = str(other_user.id)
    assert client.get(f"/runs/{run_id}").status_code == 404
    assert client.get(f"/strategies/{saved['strategy_id']}/dashboard").status_code == 404


def test_reference_series_strategy_product_loop_smoke(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _patch_synthetic_market_data(monkeypatch)

    config = _generate_config(
        client,
        "Only trade QQQ when VIX is below 25 and RSI is below 35.",
    )
    entry_rule = config["entry_rule"]
    entry_rules = entry_rule["rules"]

    assert entry_rule["kind"] == "group"
    assert entry_rule["operator"] == "AND"
    assert entry_rules[0] == {
        "kind": "atomic",
        "type": "series_below",
        "symbol": "VIX",
        "threshold": 25.0,
    }
    assert entry_rules[1] == {
        "kind": "atomic",
        "type": "rsi_below",
        "symbol": "QQQ",
        "lookback": 14,
        "threshold": 35.0,
    }
    assert "VIX" in config["reference_symbols"]

    run_id, dashboard = _create_execute_and_load_run(
        client=client,
        db_session=db_session,
        tmp_path=tmp_path,
        config=config,
    )
    assert dashboard["run"]["request_payload"]["draft_config"]["reference_symbols"] == ["VIX"]
    assert dashboard["chart_data"]["drawdown_curve"]

    _save_run_and_assert_strategy_dashboard(
        client=client,
        run_id=run_id,
        name="QQQ VIX RSI Product Loop Smoke",
    )
