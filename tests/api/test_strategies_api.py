from __future__ import annotations

import uuid

from market_simulator.db.enums import RunStatus, StrategyStatus
from market_simulator.repositories.runs import create_run, mark_run_succeeded
from market_simulator.repositories.strategies import (
    create_strategy_version,
    set_strategy_version_reference_run,
)


def _strategy_v2_config(*, symbol: str = "QQQ", entry_threshold: int = 30, exit_threshold: int = 70) -> dict:
    return {
        "schema_version": "2.0",
        "name": f"{symbol.lower()}-rsi",
        "tradable_symbol": symbol,
        "benchmark_symbol": symbol,
        "reference_symbols": [],
        "start_date": "2021-01-01",
        "end_date": "2021-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 0,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": symbol,
            "lookback": 14,
            "threshold": entry_threshold,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": symbol,
            "lookback": 14,
            "threshold": exit_threshold,
        },
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
    }


def test_get_strategy_dashboard_returns_strategy_versions_runs_and_reference_performance(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version_1 = create_strategy_bundle(user_id=current_user_ctx["id"])

    version_2 = create_strategy_version(
        db_session,
        strategy.id,
        {
            "name": "updated-strategy",
            "symbol": "QQQ",
            "benchmark": "QQQ",
            "start_date": "2020-01-01",
            "end_date": "2024-12-31",
        },
        "hash-v2",
        uuid.UUID(current_user_ctx["id"]),
    )

    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version_2.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "dashboard test"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    run = mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "total_return_pct": 42.5,
            "benchmark_return_pct": 30.1,
            "alpha_vs_benchmark_pct": 12.4,
            "cagr_pct": 7.8,
            "sharpe_ratio": 1.12,
            "max_drawdown_pct": -9.5,
            "benchmark_max_drawdown_pct": -14.0,
            "trade_count": 8,
            "win_rate_pct": 62.5,
        },
        artifact_dir="data/local_artifacts/runs/test-strategy-dashboard",
        artifact_manifest_json={
            "summary": "data/local_artifacts/runs/test-strategy-dashboard/summary.json",
        },
    )
    set_strategy_version_reference_run(
        db_session,
        version_id=version_2.id,
        run_id=run.id,
        user_id=current_user_ctx["id"],
    )

    response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert response.status_code == 200

    body = response.json()

    assert body["strategy"]["id"] == str(strategy.id)
    assert body["strategy"]["current_version_id"] == str(version_2.id)

    assert len(body["versions"]) == 2
    assert body["versions"][0]["id"] == str(version_2.id)
    assert body["versions"][0]["is_current"] is True
    assert body["versions"][0]["reference_run_id"] == str(run.id)
    assert body["versions"][1]["id"] == str(version_1.id)
    assert body["versions"][1]["is_current"] is False
    assert body["versions"][1]["reference_run_id"] is None

    assert body["total_runs"] == 1
    assert len(body["associated_runs"]) == 1
    assert body["associated_runs"][0]["run_id"] == str(run.id)
    assert body["associated_runs"][0]["status"] == "SUCCEEDED"
    assert body["associated_runs"][0]["total_return_pct"] == 42.5
    assert body["associated_runs"][0]["strategy_name"] == strategy.name
    assert body["associated_runs"][0]["strategy_version_number"] == version_2.version_number

    assert body["reference_run_id"] == str(run.id)
    assert body["reference_finished_at"] is not None
    assert body["reference_performance"]["run_id"] == str(run.id)
    assert body["reference_performance"]["total_return_pct"] == 42.5
    assert body["reference_performance"]["benchmark_return_pct"] == 30.1
    assert body["reference_performance"]["alpha_vs_benchmark_pct"] == 12.4
    assert body["reference_performance"]["trade_count"] == 8
    assert body["latest_run_id"] == body["reference_run_id"]
    assert body["latest_performance"] == body["reference_performance"]


def test_archive_strategy_sets_status_without_deleting_versions_or_runs(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "archive keeps history"},
        max_attempts=3,
    )

    response = client.post(f"/strategies/{strategy.id}/archive")

    assert response.status_code == 200
    assert response.json()["status"] == StrategyStatus.ARCHIVED

    db_session.refresh(strategy)
    assert strategy.status == StrategyStatus.ARCHIVED

    assert len(strategy.versions) == 1
    assert strategy.versions[0].id == version.id
    assert len(strategy.runs) == 1
    assert strategy.runs[0].id == run.id


def test_restore_strategy_sets_status_to_active(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, _ = create_strategy_bundle(user_id=current_user_ctx["id"])
    strategy.status = StrategyStatus.ARCHIVED
    db_session.commit()

    response = client.post(f"/strategies/{strategy.id}/restore")

    assert response.status_code == 200
    assert response.json()["status"] == StrategyStatus.ACTIVE

    db_session.refresh(strategy)
    assert strategy.status == StrategyStatus.ACTIVE


def test_list_strategies_excludes_archived_by_default_and_can_include_them(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    active_strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        strategy_name="Active Strategy",
    )
    archived_strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        strategy_name="Archived Strategy",
    )
    archived_strategy.status = StrategyStatus.ARCHIVED
    db_session.commit()

    default_response = client.get("/strategies")
    assert default_response.status_code == 200
    assert [item["id"] for item in default_response.json()] == [str(active_strategy.id)]

    include_archived_response = client.get("/strategies?include_archived=true")
    assert include_archived_response.status_code == 200
    assert {item["id"] for item in include_archived_response.json()} == {
        str(active_strategy.id),
        str(archived_strategy.id),
    }


def test_get_strategy_dashboard_returns_null_reference_performance_when_no_reference_run(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, _ = create_strategy_bundle(user_id=current_user_ctx["id"])

    response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert response.status_code == 200

    body = response.json()
    assert body["strategy"]["id"] == str(strategy.id)
    assert body["versions"][0]["reference_run_id"] is None
    assert body["total_runs"] == 0
    assert body["associated_runs"] == []
    assert body["reference_run_id"] is None
    assert body["reference_finished_at"] is None
    assert body["reference_performance"] is None
    assert body["latest_run_id"] is None
    assert body["latest_finished_at"] is None
    assert body["latest_performance"] is None


def test_get_strategy_dashboard_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, _ = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = other_user_id
    response = client.get(f"/strategies/{strategy.id}/dashboard")

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"


def test_create_strategy_version_api_creates_new_version_and_updates_current_version(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version_1 = create_strategy_bundle(user_id=current_user_ctx["id"])
    reference_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version_1.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "v1 reference"},
        max_attempts=3,
    )
    reference_run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(reference_run)
    reference_run = mark_run_succeeded(
        db_session,
        reference_run,
        summary_json={"total_return_pct": 5.0},
        artifact_dir="data/local_artifacts/runs/v1-reference",
        artifact_manifest_json={"summary": "summary.json"},
    )
    set_strategy_version_reference_run(
        db_session,
        version_id=version_1.id,
        run_id=reference_run.id,
        user_id=current_user_ctx["id"],
    )

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": {
                "name": "qqq-rsi-v2",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "start_date": "2018-01-02",
                "end_date": "2024-12-31",
                "initial_capital": 100000,
            },
            "change_note": "Adjusted entry thresholds",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["strategy_id"] == str(strategy.id)
    assert body["version_id"] != str(version_1.id)

    dashboard_response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert dashboard_response.status_code == 200

    dashboard = dashboard_response.json()
    assert dashboard["strategy"]["current_version_id"] == body["version_id"]
    assert len(dashboard["versions"]) == 2
    assert dashboard["versions"][0]["id"] == body["version_id"]
    assert dashboard["versions"][0]["version_number"] == 2
    assert dashboard["versions"][0]["change_note"] == "Adjusted entry thresholds"
    assert dashboard["versions"][0]["reference_run_id"] is None
    assert dashboard["versions"][0]["is_current"] is True
    assert dashboard["versions"][1]["id"] == str(version_1.id)
    assert dashboard["versions"][1]["reference_run_id"] == str(reference_run.id)
    assert dashboard["versions"][1]["is_current"] is False
    assert dashboard["reference_run_id"] is None
    assert dashboard["reference_performance"] is None


def test_create_strategy_version_api_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, _ = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = other_user_id

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": {
                "name": "unauthorized-version",
                "tradable_symbol": "QQQ",
            },
            "change_note": "should fail",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"


def test_create_strategy_version_rejects_tradable_symbol_identity_change(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="identity-break@example.com",
    )
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_strategy_v2_config(symbol="QQQ"),
    )

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": _strategy_v2_config(symbol="SPY"),
            "change_note": "turn this into SPY",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Changing the tradable symbol creates a different strategy. "
        "Start a new strategy from Home instead."
    )


def test_create_strategy_version_rejects_rule_symbol_identity_change(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="rule-identity-break@example.com",
    )
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_strategy_v2_config(symbol="QQQ"),
    )
    next_config = _strategy_v2_config(symbol="QQQ")
    next_config["entry_rule"] = {**next_config["entry_rule"], "symbol": "SPY"}

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": next_config,
            "change_note": "rule symbol changed",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Changing the tradable symbol creates a different strategy. "
        "Start a new strategy from Home instead."
    )


def test_create_strategy_version_allows_same_symbol_rule_threshold_change(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="same-symbol-version@example.com",
    )
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_strategy_v2_config(symbol="QQQ", entry_threshold=30),
    )

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": _strategy_v2_config(symbol="QQQ", entry_threshold=25),
            "change_note": "tighten entry threshold",
        },
    )

    assert response.status_code == 200
    dashboard_response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["versions"][0]["id"] == response.json()["version_id"]
    assert dashboard["versions"][0]["config_json"]["entry_rule"]["threshold"] == 25
    assert dashboard["versions"][0]["reference_run_id"] is None


def test_create_strategy_version_allows_benchmark_symbol_change(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="benchmark-change@example.com",
    )
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_strategy_v2_config(symbol="QQQ"),
    )
    next_config = _strategy_v2_config(symbol="QQQ")
    next_config["benchmark_symbol"] = "SPY"

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": next_config,
            "change_note": "compare QQQ against SPY",
        },
    )

    assert response.status_code == 200
    dashboard_response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["versions"][0]["config_json"]["tradable_symbol"] == "QQQ"
    assert dashboard["versions"][0]["config_json"]["benchmark_symbol"] == "SPY"
    assert dashboard["versions"][0]["config_json"]["entry_rule"]["symbol"] == "QQQ"


def test_create_strategy_version_normalizes_changed_config_name_to_strategy_name(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="version-name-normalize@example.com",
    )
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        strategy_name="QQQ RSI mean reversion",
        config_json=_strategy_v2_config(symbol="QQQ"),
    )
    next_config = _strategy_v2_config(symbol="QQQ", entry_threshold=25)
    next_config["name"] = "SPY RSI breakout"

    response = client.post(
        f"/strategies/{strategy.id}/versions",
        json={
            "config": next_config,
            "change_note": "threshold-only change",
        },
    )

    assert response.status_code == 200
    dashboard_response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["strategy"]["name"] == "QQQ RSI mean reversion"
    assert dashboard["versions"][0]["config_json"]["name"] == "QQQ RSI mean reversion"
    assert dashboard["versions"][0]["config_json"]["entry_rule"]["threshold"] == 25
    assert dashboard["versions"][0]["config_hash"] != "test-config-hash"


def test_strategy_dashboard_repairs_missing_reference_from_eligible_succeeded_run(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="dashboard-repair-reference@example.com",
    )
    strategy, version = create_strategy_bundle(
        user_id=str(user.id),
        config_json=_strategy_v2_config(symbol="QQQ"),
    )
    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {
            "source": "strategy_version_reference_run",
            "reference_strategy_version_id": str(version.id),
        },
        max_attempts=1,
    )
    run.status = RunStatus.SUCCEEDED
    run.summary_json = {"total_return_pct": 18.5}
    run.artifact_dir = f"data/local_artifacts/runs/{run.id}"
    run.artifact_manifest_json = {"summary": "summary.json"}
    db_session.commit()
    db_session.refresh(run)

    assert version.reference_run_id is None

    response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["versions"][0]["reference_run_id"] == str(run.id)
    assert dashboard["reference_run_id"] == str(run.id)
    assert dashboard["reference_performance"]["run_id"] == str(run.id)
    assert dashboard["reference_performance"]["total_return_pct"] == 18.5

    db_session.refresh(version)
    assert version.reference_run_id == run.id


def test_non_owner_run_cannot_be_set_as_strategy_version_reference(
    db_session,
    create_user,
    create_strategy_bundle,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, version = create_strategy_bundle(user_id=owner_id)
    other_run = create_run(
        db_session,
        other_user_id,
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "wrong owner"},
        max_attempts=3,
    )
    other_run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(other_run)
    other_run = mark_run_succeeded(
        db_session,
        other_run,
        summary_json={"total_return_pct": 99.0},
        artifact_dir="data/local_artifacts/runs/wrong-owner-reference",
        artifact_manifest_json={"summary": "summary.json"},
    )

    assert (
        set_strategy_version_reference_run(
            db_session,
            version_id=version.id,
            run_id=other_run.id,
            user_id=owner_id,
        )
        is None
    )
    assert (
        set_strategy_version_reference_run(
            db_session,
            version_id=version.id,
            run_id=other_run.id,
            user_id=other_user_id,
        )
        is None
    )

    db_session.refresh(version)
    assert version.reference_run_id is None
