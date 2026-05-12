from __future__ import annotations

import copy
import csv
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import market_simulator.services.strategy_builder_parsers as builder_parsers
from market_simulator.data.repository import MarketDataBundle, MarketDataRepository
from market_simulator.db.enums import RunStatus
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.artifact_store import LocalArtifactStore
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import get_run


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def beta_smoke_user(create_user, current_user_ctx):
    create_user(
        user_id=current_user_ctx["id"],
        email="beta-smoke@example.com",
    )


@pytest.fixture(autouse=True)
def deterministic_builder_metadata(monkeypatch):
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)


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


def _synthetic_vix(start_date: str, end_date: str) -> pd.DataFrame:
    dates = pd.bdate_range(start_date, end_date)
    if len(dates) < 45:
        dates = pd.bdate_range(start_date, periods=45)

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


def _generate_config(client, prompt: str) -> dict[str, Any]:
    response = client.post("/strategy-builder/generate", json={"prompt": prompt})
    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    StrategyV2.model_validate(body["config"])
    return body["config"]


def _load_gallery_templates() -> list[dict[str, Any]]:
    script = """
import('jiti').then(({ createJiti }) => {
  const jiti = createJiti(process.cwd() + '/');
  const module = jiti('./src/lib/strategyGalleryTemplates.ts');
  console.log(JSON.stringify(module.STRATEGY_GALLERY_TEMPLATES));
});
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT / "frontend",
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _template_by_id(templates: list[dict[str, Any]], template_id: str) -> dict[str, Any]:
    return next(template for template in templates if template["id"] == template_id)


def _create_execute_and_load_run(
    *,
    client,
    db_session,
    tmp_path,
    config: dict[str, Any],
    request_payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    create_response = client.post(
        "/runs",
        json={
            "draft_config": config,
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": request_payload,
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
        worker_id="beta-smoke-core-loop-worker",
        lease_seconds=300,
    )
    assert worker_result is not None
    assert worker_result["status"] == "SUCCEEDED"

    run = get_run(db_session, run_id)
    assert run.status == RunStatus.SUCCEEDED
    assert run.summary_json
    assert run.artifact_manifest_json
    assert {"summary", "timeline", "monthly_returns", "trade_log"}.issubset(
        run.artifact_manifest_json
    )

    dashboard_response = client.get(f"/runs/{run_id}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["run"]["status"] == "SUCCEEDED"
    assert dashboard["chart_data"]["equity_curve"]
    return run_id, dashboard


def _compact_config_dates(
    config: dict[str, Any],
    *,
    start_date: str = "2021-01-04",
    end_date: str = "2021-04-30",
) -> dict[str, Any]:
    compact = copy.deepcopy(config)
    compact["start_date"] = start_date
    compact["end_date"] = end_date
    StrategyV2.model_validate(compact)
    return compact


def _compact_rotation_config(config: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_config_dates(config)
    rotation = compact["rotation"]
    rotation["ranking"]["lookback"] = 21
    rotation["rebalance"]["frequency"] = "monthly"
    StrategyV2.model_validate(compact)
    return compact


def _assert_local_artifact_files(manifest: dict[str, Any], required_keys: set[str]) -> None:
    assert required_keys.issubset(manifest)
    for key in required_keys:
        uri = manifest[key]
        assert isinstance(uri, str)
        assert not uri.startswith("s3://")
        assert Path(uri).exists(), f"missing {key} artifact at {uri}"


def _assert_run_detail_chart_and_dashboard(
    *,
    client,
    run_id: str,
    current_user_id: str,
) -> dict[str, Any]:
    detail_response = client.get(f"/runs/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == run_id
    assert detail["user_id"] == current_user_id
    assert detail["status"] == "SUCCEEDED"
    assert detail["summary_json"]["total_return_pct"] is not None

    manifest = detail["artifact_manifest_json"]
    _assert_local_artifact_files(
        manifest,
        {"summary", "timeline", "monthly_returns", "trade_log", "report_bundle"},
    )

    chart_response = client.get(f"/runs/{run_id}/chart-data")
    assert chart_response.status_code == 200
    chart_data = chart_response.json()
    assert chart_data["run_id"] == run_id
    assert chart_data["equity_curve"]
    assert chart_data["drawdown_curve"]

    dashboard_response = client.get(f"/runs/{run_id}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["run"]["id"] == run_id
    assert dashboard["run"]["status"] == "SUCCEEDED"
    assert dashboard["chart_data"]["equity_curve"]
    return dashboard


def _assert_rotation_artifacts_and_review(*, client, db_session, run_id: str) -> None:
    run = get_run(db_session, run_id)
    assert run.summary_json["strategy_type"] == "rotation"
    assert run.summary_json["rebalance_count"] >= 1

    timeline_path = Path(run.artifact_manifest_json["timeline"])
    with timeline_path.open(newline="", encoding="utf-8") as timeline_file:
        reader = csv.DictReader(timeline_file)
        assert {"selected_assets", "target_weights", "asset_ranks", "rebalance"}.issubset(
            reader.fieldnames or []
        )
        rebalance_rows = [
            row
            for row in reader
            if str(row.get("rebalance", "")).strip().lower() == "true"
        ]

    assert rebalance_rows
    assert any(row.get("asset_ranks") not in (None, "", "{}") for row in rebalance_rows)

    dashboard_response = client.get(f"/runs/{run_id}/dashboard")
    assert dashboard_response.status_code == 200
    rotation_review = dashboard_response.json()["rotation_review"]
    assert rotation_review["is_rotation"] is True
    assert rotation_review["metrics"]["rebalance_count"] >= 1
    assert rotation_review["total_count"] >= 1
    assert rotation_review["rebalances"]
    assert any(event["asset_ranks"] for event in rotation_review["rebalances"])


def _assert_compare_outputs(client, *, run_ids: list[str], current_user_id: str) -> None:
    for run_id in run_ids:
        detail_response = client.get(f"/runs/{run_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["user_id"] == current_user_id

    run_id_param = ",".join(run_ids)
    compare_response = client.get(f"/runs/compare?run_ids={run_id_param}")
    assert compare_response.status_code == 200
    comparison = compare_response.json()
    assert {row["run_id"] for row in comparison["runs"]} == set(run_ids)
    assert all(row["status"] == "SUCCEEDED" for row in comparison["runs"])
    assert all(row["total_return_pct"] is not None for row in comparison["runs"])
    assert comparison["metadata"]["run_windows"]

    chart_response = client.get(f"/runs/compare/chart?run_ids={run_id_param}")
    assert chart_response.status_code == 200
    chart = chart_response.json()
    assert len(chart["strategy_curves"]) == len(run_ids)
    assert all(curve["points"] for curve in chart["strategy_curves"])
    assert chart["benchmark_curves"]


def test_beta_smoke_core_loop_builder_gallery_rotation_and_compare(
    client,
    db_session,
    monkeypatch,
    tmp_path,
    current_user_ctx,
):
    _patch_synthetic_market_data(monkeypatch)

    builder_config = _generate_config(
        client,
        (
            "Create a QQQ mean reversion strategy from 2021-01-04 to 2021-04-30 "
            "with RSI below 35 and exit when RSI is above 65."
        ),
    )
    builder_config = _compact_config_dates(builder_config)
    assert builder_config["tradable_symbol"] == "QQQ"
    assert builder_config["entry_rule"]["type"] == "rsi_below"

    builder_run_id, _ = _create_execute_and_load_run(
        client=client,
        db_session=db_session,
        tmp_path=tmp_path,
        config=builder_config,
        request_payload={"source": "beta_smoke_builder"},
    )
    _assert_run_detail_chart_and_dashboard(
        client=client,
        run_id=builder_run_id,
        current_user_id=current_user_ctx["id"],
    )

    gallery_template = _template_by_id(_load_gallery_templates(), "qqq-core-rsi-starter")
    gallery_config = _compact_config_dates(gallery_template["config"])
    assert gallery_config["name"]

    gallery_run_id, _ = _create_execute_and_load_run(
        client=client,
        db_session=db_session,
        tmp_path=tmp_path,
        config=gallery_config,
        request_payload={
            "source": "strategy_gallery",
            "template_id": gallery_template["id"],
            "template_title": gallery_template["title"],
        },
    )
    _assert_run_detail_chart_and_dashboard(
        client=client,
        run_id=gallery_run_id,
        current_user_id=current_user_ctx["id"],
    )

    rotation_config = _generate_config(
        client,
        (
            "Create a monthly rotation between QQQ, SPY, XLK, and TLT using "
            "21-day momentum from 2021-01-04 to 2021-04-30."
        ),
    )
    rotation_config = _compact_rotation_config(rotation_config)
    assert rotation_config["rotation"]["enabled"] is True
    assert rotation_config["rotation"]["selection"]["top_n"] == 1

    rotation_run_id, _ = _create_execute_and_load_run(
        client=client,
        db_session=db_session,
        tmp_path=tmp_path,
        config=rotation_config,
        request_payload={"source": "beta_smoke_rotation_builder"},
    )
    _assert_run_detail_chart_and_dashboard(
        client=client,
        run_id=rotation_run_id,
        current_user_id=current_user_ctx["id"],
    )
    _assert_rotation_artifacts_and_review(
        client=client,
        db_session=db_session,
        run_id=rotation_run_id,
    )

    _assert_compare_outputs(
        client,
        run_ids=[builder_run_id, gallery_run_id],
        current_user_id=current_user_ctx["id"],
    )
