from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from market_simulator import settings as settings_module
from market_simulator.data.repository import MarketDataBundle, MarketDataRepository
from market_simulator.db.enums import RunStatus
from market_simulator.platform.services.artifact_store import LocalArtifactStore
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import get_run
from market_simulator.services.model_signal_catalog import build_model_signal_strategy_config
from market_simulator.settings import Settings


MODEL_VERSION = "linear_smooth10_margin002_v1"
HISTORICAL_SYMBOLS = ("QQQ", "SLV")
CURRENT_SYMBOL = "VUG"


def _synthetic_etf_bars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    dates = pd.bdate_range(start_date, end_date)
    if len(dates) < 45:
        dates = pd.bdate_range(start_date, periods=45)

    closes = []
    for index in range(len(dates)):
        symbol_offset = (sum(ord(char) for char in symbol) % 7) * 0.08
        if index < 22:
            close = 120.0 - index * (1.0 + symbol_offset)
        elif index < 55:
            close = 98.0 + (index - 22) * (1.1 + symbol_offset)
        else:
            close = 134.0 + math.sin(index / 3) * 2.0 + symbol_offset
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


def _patch_synthetic_market_data(monkeypatch) -> None:
    def fake_get_market_data(
        self,
        tradable_symbol: str,
        reference_symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> MarketDataBundle:
        return MarketDataBundle(
            tradable=_synthetic_etf_bars(tradable_symbol, start_date, end_date),
            references={
                symbol: _synthetic_etf_bars(symbol, start_date, end_date)
                for symbol in reference_symbols
            },
        )

    monkeypatch.setattr(MarketDataRepository, "get_market_data", fake_get_market_data)


def _score_rows(date: str, *, selected_symbol: str) -> list[dict[str, Any]]:
    rows = []
    unselected_scores = {"QQQ": 0.3, "SLV": 0.2, "VUG": 0.1}
    unselected_ranks = {"QQQ": 2, "SLV": 3, "VUG": 4}
    for symbol in ("QQQ", "SLV", "VUG"):
        selected = symbol == selected_symbol
        rows.append(
            {
                "date": date,
                "symbol": symbol,
                "model_version": MODEL_VERSION,
                "score": 0.95 if selected else unselected_scores[symbol],
                "rank": 1 if selected else unselected_ranks[symbol],
                "confidence": 0.9,
                "signal_bucket": "top",
            }
        )
    return rows


def _write_model_signal_artifact(
    base_path: Path,
    *,
    selected_by_date: dict[str, str],
    manifest_artifact_path: str,
) -> None:
    version_dir = base_path / f"model_version={MODEL_VERSION}"
    version_dir.mkdir(parents=True)
    rows = [
        row
        for date, selected_symbol in selected_by_date.items()
        for row in _score_rows(date, selected_symbol=selected_symbol)
    ]
    pd.DataFrame(rows).to_csv(version_dir / "signals.csv", index=False)
    latest_date = max(selected_by_date)
    (version_dir / "model_signal_manifest.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "latest_signal_date": latest_date,
                "status": "ready",
                "warnings": ["synthetic model-signal platform smoke fixture"],
                "artifact_path": manifest_artifact_path,
            }
        ),
        encoding="utf-8",
    )


def _model_signal_config() -> dict[str, Any]:
    return build_model_signal_strategy_config(
        model_version=MODEL_VERSION,
        start_date="2021-01-04",
        end_date="2021-04-30",
        universe=["QQQ", "SLV", "VUG"],
        top_n=1,
        signal_bucket_filter=["top"],
        fallback={"type": "cash"},
        name="Model Signal Path Separation Smoke",
        initial_capital=100_000,
        transaction_cost_bps=5,
    )


def _create_execute_and_load_model_signal_run(
    *,
    client,
    db_session,
    tmp_path: Path,
    config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    create_response = client.post(
        "/runs",
        json={
            "draft_config": config,
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"source": "model_signal_platform_smoke"},
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
        worker_id="model-signal-platform-smoke-worker",
        lease_seconds=300,
    )
    assert worker_result is not None
    assert worker_result["status"] == "SUCCEEDED"

    run = get_run(db_session, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.summary_json["strategy_type"] == "model_signal"
    assert run.artifact_manifest_json
    return run_id, run.artifact_manifest_json


def _rebalance_selected_assets(timeline_path: Path) -> list[str]:
    selected_assets = []
    with timeline_path.open(newline="", encoding="utf-8") as timeline_file:
        for row in csv.DictReader(timeline_file):
            if str(row.get("rebalance", "")).strip().lower() == "true":
                selected_assets.append(row.get("selected_assets", ""))
                assert float(row.get("overlay_position_market_value") or 0.0) > 0.0
    return selected_assets


def test_model_signal_platform_smoke_separates_historical_and_current_artifacts(
    real_auth_client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
    tmp_path,
) -> None:
    _patch_synthetic_market_data(monkeypatch)
    real_auth_client.headers.update({"X-User-Id": current_user_ctx["id"]})
    create_user(user_id=current_user_ctx["id"])

    historical_path = tmp_path / "historical_model_signals"
    current_path = tmp_path / "current_model_signals"
    _write_model_signal_artifact(
        historical_path,
        selected_by_date={
            "2021-01-04": "QQQ",
            "2021-02-01": "SLV",
            "2021-03-01": "QQQ",
            "2021-04-01": "SLV",
        },
        manifest_artifact_path="/Users/private/historical/signals.parquet",
    )
    _write_model_signal_artifact(
        current_path,
        selected_by_date={"2026-05-08": CURRENT_SYMBOL},
        manifest_artifact_path="/Users/private/current/signals.parquet",
    )
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            model_signal_data_path=str(historical_path),
            model_signal_current_data_path=str(current_path),
            artifact_storage_backend="LOCAL",
        ),
    )

    preview_response = real_auth_client.get(
        f"/model-signals/catalog/{MODEL_VERSION}/current"
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["selected_symbols"] == [CURRENT_SYMBOL]
    assert preview["source"]["label"] == "current artifact"
    preview_payload = json.dumps(preview)
    assert str(historical_path) not in preview_payload
    assert str(current_path) not in preview_payload
    assert "/Users/private" not in preview_payload

    config = _model_signal_config()
    run_id, artifact_manifest = _create_execute_and_load_model_signal_run(
        client=real_auth_client,
        db_session=db_session,
        tmp_path=tmp_path,
        config=config,
    )
    run = get_run(db_session, run_id)
    assert run.summary_json["trade_event_count"] > 1
    assert run.summary_json["final_cash"] < run.summary_json["initial_capital"]

    selected_assets = _rebalance_selected_assets(Path(artifact_manifest["timeline"]))
    assert selected_assets
    assert any(symbol in ",".join(selected_assets) for symbol in HISTORICAL_SYMBOLS)
    assert CURRENT_SYMBOL not in ",".join(selected_assets)

    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=config,
    )
    signal_response = real_auth_client.get(
        f"/strategies/{strategy.id}/current-signal?strategy_version_id={version.id}"
    )
    assert signal_response.status_code == 200
    current_signal = signal_response.json()
    assert current_signal["selected_symbols"] == [CURRENT_SYMBOL]
    assert current_signal["source"]["label"] == "current artifact"
    signal_payload = json.dumps(current_signal)
    assert str(historical_path) not in signal_payload
    assert str(current_path) not in signal_payload
    assert "/Users/private" not in signal_payload

    owner_id = "00000000-0000-0000-0000-000000000022"
    create_user(user_id=owner_id)
    other_strategy, _ = create_strategy_bundle(
        user_id=owner_id,
        config_json=config,
    )
    non_owner_response = real_auth_client.get(
        f"/strategies/{other_strategy.id}/current-signal"
    )
    assert non_owner_response.status_code == 404
