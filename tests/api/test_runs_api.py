from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from market_simulator.db.enums import RunStatus, SubscriptionStatus
from market_simulator.db.models import Plan, UserPlanSubscription
from market_simulator.repositories.plans import count_runs_created_today
from market_simulator.repositories.runs import create_run, get_run, mark_run_succeeded

def create_plan(
    db_session,
    *,
    code: str,
    builder_prompt_daily_limit: int,
    builder_prompt_max_chars: int,
    max_backtest_years: int,
    max_saved_strategies: int = 50,
):
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=code.title(),
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=50,
        max_saved_strategies=max_saved_strategies,
        max_tracked_strategies=50,
        allow_ai_builder=True,
        allow_portfolio_runs=True,
        allow_comparison_runs=True,
        allow_parameter_sweeps=True,
        allow_strategy_history=True,
        builder_prompt_daily_limit=builder_prompt_daily_limit,
        builder_prompt_max_chars=builder_prompt_max_chars,
        max_backtest_years=max_backtest_years,
        max_comparison_runs=4,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def attach_plan(db_session, *, user_id: str, plan_id: str):
    existing = (
        db_session.query(UserPlanSubscription)
        .filter(
            UserPlanSubscription.user_id == user_id,
            UserPlanSubscription.status == SubscriptionStatus.ACTIVE,
        )
        .all()
    )
    for row in existing:
        row.status = SubscriptionStatus.CANCELED
        row.ends_at = datetime.now(timezone.utc)

    user_plan = UserPlanSubscription(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_id=plan_id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ends_at=None,
        auto_renew=False,
    )
    db_session.add(user_plan)
    db_session.commit()
    db_session.refresh(user_plan)
    return user_plan


def _create_run_via_api(
    client,
    *,
    strategy_id: str,
    strategy_version_id: str,
    run_type: str = "SIMULATION",
    executor_type: str = "SIMULATION_EXECUTOR",
    request_payload: dict | None = None,
    max_attempts: int = 3,
):
    response = client.post(
        "/runs",
        json={
            "strategy_id": strategy_id,
            "strategy_version_id": strategy_version_id,
            "run_type": run_type,
            "executor_type": executor_type,
            "request_payload": request_payload or {},
            "max_attempts": max_attempts,
        },
    )
    assert response.status_code == 200
    return response.json()


def _create_succeeded_run(
    db_session,
    *,
    user_id: str,
    strategy_id: str,
    strategy_version_id: str,
    note: str,
):
    run = create_run(
        db_session,
        user_id,
        strategy_id,
        strategy_version_id,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": note},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    return mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 10.0},
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"summary": f"dummy-{run.id}"},
    )


def _mock_compare_chart_windows(monkeypatch, windows_by_summary_ref: dict[str, tuple[str, str]]):
    def fake_load_chart_data(manifest):
        start_date, end_date = windows_by_summary_ref[manifest["summary"]]
        return {
            "equity_curve": [
                {"date": start_date, "strategy_equity": 100000.0, "benchmark_equity": 100000.0},
                {"date": end_date, "strategy_equity": 110000.0, "benchmark_equity": 105000.0},
            ],
            "drawdown_curve": [],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        fake_load_chart_data,
    )


def _strategy_v2_config() -> dict:
    return {
        "schema_version": "2.0",
        "name": "qqq-rsi",
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "QQQ",
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
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 30,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": "QQQ",
            "lookback": 14,
            "threshold": 70,
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


def _create_succeeded_sweep_with_variants(
    db_session,
    *,
    user_id: str,
    base_config: dict | None = None,
):
    config = base_config or _strategy_v2_config()
    variant_a_config = {**config, "name": "qqq-rsi-sweep-entry-20-exit-70"}
    variant_a_config["entry_rule"] = {**config["entry_rule"], "threshold": 20}
    variant_b_config = {**config, "name": "qqq-rsi-sweep-entry-40-exit-80"}
    variant_b_config["entry_rule"] = {**config["entry_rule"], "threshold": 40}
    variant_b_config["exit_rule"] = {**config["exit_rule"], "threshold": 80}

    run = create_run(
        db_session,
        user_id,
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {
            "base_config": config,
            "grid": {
                "entry_rule.threshold": [20, 40],
                "exit_rule.threshold": [70, 80],
            },
        },
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    return mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": "sharpe_ratio",
            "variant_count": 2,
            "best_variant": {
                "variant_id": "variant-a",
                "variant_name": variant_a_config["name"],
                "parameters": {"entry_rule.threshold": 20, "exit_rule.threshold": 70},
                "status": "SUCCEEDED",
                "total_return_pct": 12.5,
                "benchmark_return_pct": 8.0,
                "alpha_vs_benchmark_pct": 4.5,
                "cagr_pct": 11.0,
                "sharpe_ratio": 1.5,
                "max_drawdown_pct": -5.5,
                "trade_count": 8,
                "artifact_dir": f"data/local_artifacts/runs/{run.id}/variants/variant-a",
                "config": variant_a_config,
            },
            "results": [
                {
                    "variant_id": "variant-a",
                    "variant_name": variant_a_config["name"],
                    "parameters": {"entry_rule.threshold": 20, "exit_rule.threshold": 70},
                    "status": "SUCCEEDED",
                    "total_return_pct": 12.5,
                    "benchmark_return_pct": 8.0,
                    "alpha_vs_benchmark_pct": 4.5,
                    "cagr_pct": 11.0,
                    "sharpe_ratio": 1.5,
                    "max_drawdown_pct": -5.5,
                    "trade_count": 8,
                    "artifact_dir": f"data/local_artifacts/runs/{run.id}/variants/variant-a",
                    "config": variant_a_config,
                },
                {
                    "variant_id": "variant-b",
                    "variant_name": variant_b_config["name"],
                    "parameters": {"entry_rule.threshold": 40, "exit_rule.threshold": 80},
                    "status": "SUCCEEDED",
                    "total_return_pct": 9.5,
                    "benchmark_return_pct": 8.0,
                    "alpha_vs_benchmark_pct": 1.5,
                    "cagr_pct": 8.7,
                    "sharpe_ratio": 1.1,
                    "max_drawdown_pct": -7.0,
                    "trade_count": 9,
                    "artifact_dir": f"data/local_artifacts/runs/{run.id}/variants/variant-b",
                    "config": variant_b_config,
                },
            ],
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": f"data/local_artifacts/runs/{run.id}/sweep_summary.json"},
    )


def _mock_comparable_chart_data(monkeypatch):
    def fake_load_chart_data(manifest):
        summary_ref = manifest["summary"]
        if "variant-a" in summary_ref:
            return {
                "equity_curve": [
                    {"date": "2024-01-01", "strategy_equity": 100.0, "benchmark_equity": 100.0},
                    {"date": "2024-01-02", "strategy_equity": 112.5, "benchmark_equity": 108.0},
                ],
                "drawdown_curve": [
                    {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                    {"date": "2024-01-02", "strategy_drawdown_pct": -5.5, "benchmark_drawdown_pct": -2.0},
                ],
                "monthly_returns": [],
                "sleeve_equity_curve": [],
                "sleeve_weight_curve": [],
                "trade_markers": [],
            }
        if "variant-b" in summary_ref:
            return {
                "equity_curve": [
                    {"date": "2024-01-01", "strategy_equity": 100.0, "benchmark_equity": 100.0},
                    {"date": "2024-01-02", "strategy_equity": 109.5, "benchmark_equity": 108.0},
                ],
                "drawdown_curve": [
                    {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                    {"date": "2024-01-02", "strategy_drawdown_pct": -7.0, "benchmark_drawdown_pct": -2.0},
                ],
                "monthly_returns": [],
                "sleeve_equity_curve": [],
                "sleeve_weight_curve": [],
                "trade_markers": [],
            }

        return {
            "equity_curve": [
                {"date": "2024-01-01", "strategy_equity": 100.0, "benchmark_equity": 100.0},
                {"date": "2024-01-02", "strategy_equity": 110.0, "benchmark_equity": 105.0},
            ],
            "drawdown_curve": [
                {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-01-02", "strategy_drawdown_pct": -4.0, "benchmark_drawdown_pct": -1.0},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        fake_load_chart_data,
    )


def test_create_run_returns_pending(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    response = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "api create test"},
            "max_attempts": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "PENDING"
    assert body["strategy_id"] == str(strategy.id)
    assert body["strategy_version_id"] == str(version.id)
    assert body["strategy_name"] == strategy.name
    assert body["strategy_version_number"] == version.version_number
    assert body["attempt_count"] == 0
    assert body["max_attempts"] == 3
    assert body["progress_message"] == "Run created"


def test_create_and_enqueue_version_run_uses_strategy_version_and_payload_dates(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="run-version@example.com",
    )
    version_config = _strategy_v2_config()
    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=version_config,
    )

    response = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {
                "source": "strategy_version_reference_run",
                "set_as_reference_on_success": True,
                "reference_strategy_version_id": str(version.id),
                "start_date": version_config["start_date"],
                "end_date": version_config["end_date"],
            },
            "max_attempts": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["strategy_id"] == str(strategy.id)
    assert body["strategy_version_id"] == str(version.id)
    assert body["request_payload"]["start_date"] == version_config["start_date"]
    assert body["request_payload"]["end_date"] == version_config["end_date"]
    assert body["request_payload"]["set_as_reference_on_success"] is True
    assert body["request_payload"]["reference_strategy_version_id"] == str(version.id)

    enqueue_response = client.post(f"/runs/{body['id']}/enqueue")
    assert enqueue_response.status_code == 200
    assert enqueue_response.json()["status"] == "QUEUED"


def test_create_strategy_version_run_enforces_backtest_date_plan_limit(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="version-date-limit@example.com",
    )
    plan = db_session.query(Plan).filter(Plan.code == "TEST_PRO").one()
    plan.max_backtest_years = 1
    db_session.commit()

    long_config = _strategy_v2_config()
    long_config["start_date"] = "2021-01-01"
    long_config["end_date"] = "2024-01-01"
    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=long_config,
    )

    response = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 400
    assert "plan limit of 1 years" in response.json()["detail"]


def test_reference_on_success_version_run_sets_reference_and_later_runs_do_not_overwrite(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="auto-reference@example.com",
    )
    strategy, version = create_strategy_bundle(
        user_id=str(user.id),
        config_json=_strategy_v2_config(),
    )

    first_run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {
            "source": "strategy_version_reference_run",
            "set_as_reference_on_success": True,
            "reference_strategy_version_id": str(version.id),
        },
        max_attempts=1,
    )
    first_run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(first_run)
    first_run = mark_run_succeeded(
        db_session,
        first_run,
        summary_json={"total_return_pct": 10.0},
        artifact_dir=f"data/local_artifacts/runs/{first_run.id}",
        artifact_manifest_json={"summary": f"dummy-{first_run.id}"},
    )
    db_session.refresh(version)
    assert version.reference_run_id == first_run.id

    second_run = _create_succeeded_run(
        db_session,
        user_id=str(user.id),
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="later run",
    )
    db_session.refresh(version)
    assert version.reference_run_id == first_run.id
    assert version.reference_run_id != second_run.id


def test_strategy_dashboard_shows_reference_after_version_run_succeeds(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="dashboard-reference-after-run@example.com",
    )
    strategy, version = create_strategy_bundle(
        user_id=str(user.id),
        config_json=_strategy_v2_config(),
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
            "set_as_reference_on_success": True,
            "reference_strategy_version_id": str(version.id),
        },
        max_attempts=1,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    run = mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 10.0},
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"summary": f"dummy-{run.id}"},
    )

    response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["versions"][0]["reference_run_id"] == str(run.id)
    assert dashboard["reference_run_id"] == str(run.id)
    assert dashboard["reference_performance"]["run_id"] == str(run.id)
    assert dashboard["reference_performance"]["total_return_pct"] == 10.0


def test_source_marked_version_run_sets_reference_without_boolean_flag(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="source-reference@example.com",
    )
    strategy, version = create_strategy_bundle(
        user_id=str(user.id),
        config_json=_strategy_v2_config(),
    )

    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"source": "strategy_version_reference_run"},
        max_attempts=1,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    run = mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 13.0},
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"summary": f"dummy-{run.id}"},
    )

    db_session.refresh(version)
    assert version.reference_run_id == run.id


def test_create_parameter_sweep_rejects_over_limit_grid(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="sweep-limit@example.com",
    )

    response = client.post(
        "/runs",
        json={
            "run_type": "PARAMETER_SWEEP",
            "executor_type": "SWEEP_EXECUTOR",
            "request_payload": {
                "base_config": _strategy_v2_config(),
                "grid": {
                    "entry_rule.threshold": [20, 25],
                    "exit_rule.threshold": [60, 65],
                },
                "max_variants": 3,
            },
            "max_attempts": 3,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Parameter sweep is limited to 3 variants for your plan."


def test_promote_sweep_variant_for_saved_strategy_creates_current_version(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="sweep-promote-version@example.com",
    )
    base_config = _strategy_v2_config()
    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=base_config,
    )
    variant_config = {**base_config, "name": "qqq-rsi-sweep-001-threshold-25"}
    variant_config["entry_rule"] = {**base_config["entry_rule"], "threshold": 25}

    run = create_run(
        db_session,
        str(user.id),
        str(strategy.id),
        str(version.id),
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"grid": {"entry_rule.threshold": [25]}},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": "sharpe_ratio",
            "variant_count": 1,
            "best_variant": {
                "variant_id": "variant-best",
                "variant_name": variant_config["name"],
                "parameters": {"entry_rule.threshold": 25},
                "status": "SUCCEEDED",
                "config": variant_config,
            },
            "results": [
                {
                    "variant_id": "variant-best",
                    "variant_name": variant_config["name"],
                    "parameters": {"entry_rule.threshold": 25},
                    "status": "SUCCEEDED",
                    "config": variant_config,
                }
            ],
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": "sweep_summary.json"},
    )

    response = client.post(f"/runs/{run.id}/sweep/variants/variant-best/promote", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == str(strategy.id)
    assert body["version_id"] != str(version.id)
    assert body["derived_run_id"] is not None

    dashboard_response = client.get(f"/strategies/{strategy.id}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["strategy"]["current_version_id"] == body["version_id"]
    assert dashboard["versions"][0]["config_json"]["entry_rule"]["threshold"] == 25
    assert dashboard["versions"][0]["reference_run_id"] == body["derived_run_id"]
    assert dashboard["reference_run_id"] == body["derived_run_id"]
    assert dashboard["reference_performance"]["run_id"] == body["derived_run_id"]
    assert dashboard["reference_performance"]["source"] == "sweep_variant_save"
    assert dashboard["reference_performance"]["source_sweep_run_id"] == str(run.id)
    assert dashboard["reference_performance"]["source_variant_id"] == "variant-best"
    assert dashboard["versions"][0]["change_note"].startswith(
        f"Promoted from parameter sweep run {str(run.id).split('-')[0]}, rank #1."
    )

    derived_run_response = client.get(f"/runs/{body['derived_run_id']}")
    assert derived_run_response.status_code == 200
    derived_run = derived_run_response.json()
    assert derived_run["strategy_id"] == str(strategy.id)
    assert derived_run["strategy_version_id"] == body["version_id"]
    assert derived_run["parent_run_id"] == str(run.id)
    assert derived_run["source"] == "sweep_variant_save"

    detail_response = client.get(f"/runs/{run.id}/sweep/variants/variant-best")
    assert detail_response.status_code == 200
    assert detail_response.json()["sweep_origin"] == "SAVED_STRATEGY"


def test_promote_sweep_variant_without_saved_strategy_creates_strategy(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="sweep-promote-strategy@example.com",
    )
    base_config = _strategy_v2_config()
    variant_config = {**base_config, "name": "qqq-rsi-sweep-001-threshold-20"}
    variant_config["entry_rule"] = {**base_config["entry_rule"], "threshold": 20}
    sibling_variant_config = {**base_config, "name": "qqq-rsi-sweep-001-threshold-25"}
    sibling_variant_config["entry_rule"] = {**base_config["entry_rule"], "threshold": 25}

    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"base_config": base_config, "grid": {"entry_rule.threshold": [20]}},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": "sharpe_ratio",
            "variant_count": 2,
            "best_variant": {
                "variant_id": "variant-new",
                "variant_name": variant_config["name"],
                "parameters": {"entry_rule.threshold": 20},
                "status": "SUCCEEDED",
                "config": variant_config,
            },
            "results": [
                {
                    "variant_id": "variant-new",
                    "variant_name": variant_config["name"],
                    "parameters": {"entry_rule.threshold": 20},
                    "status": "SUCCEEDED",
                    "total_return_pct": 12.3,
                    "benchmark_return_pct": 8.0,
                    "alpha_vs_benchmark_pct": 4.3,
                    "cagr_pct": 11.8,
                    "sharpe_ratio": 1.4,
                    "max_drawdown_pct": -6.5,
                    "trade_count": 9,
                    "config": variant_config,
                },
                {
                    "variant_id": "variant-sibling",
                    "variant_name": sibling_variant_config["name"],
                    "parameters": {"entry_rule.threshold": 25},
                    "status": "SUCCEEDED",
                    "total_return_pct": 10.5,
                    "benchmark_return_pct": 8.0,
                    "alpha_vs_benchmark_pct": 2.5,
                    "cagr_pct": 10.0,
                    "sharpe_ratio": 1.2,
                    "max_drawdown_pct": -7.1,
                    "trade_count": 8,
                    "config": sibling_variant_config,
                }
            ],
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": "sweep_summary.json"},
    )

    response = client.post(f"/runs/{run.id}/sweep/variants/variant-new/promote", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"]
    assert body["version_id"]
    assert body["derived_run_id"]

    dashboard_response = client.get(f"/strategies/{body['strategy_id']}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["strategy"]["name"] == "qqq-rsi-sweep-001-threshold-20 - Sweep best"
    assert dashboard["versions"][0]["config_json"]["entry_rule"]["threshold"] == 20
    assert dashboard["versions"][0]["reference_run_id"] == body["derived_run_id"]
    assert dashboard["total_runs"] == 0
    assert dashboard["associated_runs"] == []
    assert dashboard["reference_run_id"] == body["derived_run_id"]
    assert dashboard["reference_performance"]["run_id"] == body["derived_run_id"]
    assert dashboard["reference_performance"]["source"] == "sweep_variant_save"
    assert dashboard["reference_performance"]["source_sweep_run_id"] == str(run.id)
    assert dashboard["reference_performance"]["source_variant_id"] == "variant-new"
    assert dashboard["reference_performance"]["source_variant_rank"] == 1
    assert dashboard["reference_performance"]["source_ranking_metric"] == "sharpe_ratio"
    assert dashboard["reference_performance"]["total_return_pct"] == 12.3
    assert dashboard["latest_run_id"] == body["derived_run_id"]
    assert dashboard["latest_performance"]["run_id"] == body["derived_run_id"]
    assert dashboard["latest_performance"]["source"] == "sweep_variant_save"
    assert dashboard["latest_performance"]["source_sweep_run_id"] == str(run.id)
    assert dashboard["latest_performance"]["source_variant_id"] == "variant-new"
    assert dashboard["latest_performance"]["source_variant_rank"] == 1
    assert dashboard["latest_performance"]["source_ranking_metric"] == "sharpe_ratio"
    assert dashboard["latest_performance"]["total_return_pct"] == 12.3

    derived_run_response = client.get(f"/runs/{body['derived_run_id']}")
    assert derived_run_response.status_code == 200
    derived_run = derived_run_response.json()
    assert derived_run["strategy_id"] == body["strategy_id"]
    assert derived_run["strategy_version_id"] == body["version_id"]
    assert derived_run["parent_run_id"] == str(run.id)
    assert derived_run["status"] == "SUCCEEDED"
    assert derived_run["source"] == "sweep_variant_save"
    assert derived_run["source_sweep_run_id"] == str(run.id)
    assert derived_run["source_variant_id"] == "variant-new"
    assert derived_run["source_variant_rank"] == 1
    assert derived_run["source_ranking_metric"] == "sharpe_ratio"
    assert derived_run["request_payload"]["source"] == "sweep_variant_save"
    assert derived_run["request_payload"]["source_variant_id"] == "variant-new"
    assert derived_run["request_payload"]["source_variant_rank"] == 1
    assert derived_run["request_payload"]["source_ranking_metric"] == "sharpe_ratio"

    derived_dashboard_response = client.get(f"/runs/{body['derived_run_id']}/dashboard")
    assert derived_dashboard_response.status_code == 200
    assert count_runs_created_today(db_session, str(user.id)) == 1

    hidden_runs_dashboard_response = client.get(f"/runs/dashboard?strategy_id={body['strategy_id']}")
    assert hidden_runs_dashboard_response.status_code == 200
    hidden_runs_dashboard = hidden_runs_dashboard_response.json()
    assert hidden_runs_dashboard["items"] == []
    assert hidden_runs_dashboard["total"] == 0

    runs_dashboard_response = client.get(
        f"/runs/dashboard?strategy_id={body['strategy_id']}&include_derived_results=true"
    )
    assert runs_dashboard_response.status_code == 200
    runs_dashboard = runs_dashboard_response.json()
    assert runs_dashboard["items"][0]["run_id"] == body["derived_run_id"]
    assert runs_dashboard["items"][0]["source"] == "sweep_variant_save"
    assert runs_dashboard["items"][0]["source_variant_id"] == "variant-new"

    run_response = client.get(f"/runs/{run.id}")
    assert run_response.status_code == 200
    assert run_response.json()["strategy_id"] is None
    assert run_response.json()["strategy_version_id"] is None

    saved_detail_response = client.get(f"/runs/{run.id}/sweep/variants/variant-new")
    assert saved_detail_response.status_code == 200
    saved_detail = saved_detail_response.json()
    assert saved_detail["sweep_origin"] == "STANDALONE"
    assert saved_detail["saved_strategy_id"] == body["strategy_id"]
    assert saved_detail["saved_version_id"] == body["version_id"]
    assert saved_detail["saved_run_id"] == body["derived_run_id"]

    duplicate_response = client.post(f"/runs/{run.id}/sweep/variants/variant-new/promote", json={})
    assert duplicate_response.status_code == 200
    duplicate_body = duplicate_response.json()
    assert duplicate_body["strategy_id"] == body["strategy_id"]
    assert duplicate_body["version_id"] == body["version_id"]
    assert duplicate_body["derived_run_id"] == body["derived_run_id"]

    sibling_detail_response = client.get(f"/runs/{run.id}/sweep/variants/variant-sibling")
    assert sibling_detail_response.status_code == 200
    assert sibling_detail_response.json()["sweep_origin"] == "STANDALONE"
    assert sibling_detail_response.json()["run"]["strategy_id"] is None
    assert sibling_detail_response.json()["saved_strategy_id"] is None

    sibling_save_response = client.post(
        f"/runs/{run.id}/sweep/variants/variant-sibling/promote",
        json={"name": "Saved sibling variant"},
    )
    assert sibling_save_response.status_code == 200
    sibling_body = sibling_save_response.json()
    assert sibling_body["strategy_id"] != body["strategy_id"]
    assert sibling_body["derived_run_id"] != body["derived_run_id"]

    sibling_dashboard_response = client.get(f"/strategies/{sibling_body['strategy_id']}/dashboard")
    assert sibling_dashboard_response.status_code == 200
    sibling_dashboard = sibling_dashboard_response.json()
    assert sibling_dashboard["versions"][0]["config_json"]["entry_rule"]["threshold"] == 25
    assert sibling_dashboard["versions"][0]["reference_run_id"] == sibling_body["derived_run_id"]
    assert sibling_dashboard["reference_run_id"] == sibling_body["derived_run_id"]
    assert sibling_dashboard["latest_run_id"] == sibling_body["derived_run_id"]
    assert count_runs_created_today(db_session, str(user.id)) == 1

    normal_run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "normal user-triggered run"},
        max_attempts=1,
    )
    normal_run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(normal_run)
    mark_run_succeeded(
        db_session,
        normal_run,
        summary_json={"total_return_pct": 2.0},
        artifact_dir=f"data/local_artifacts/runs/{normal_run.id}",
        artifact_manifest_json={"summary": "summary.json"},
    )

    default_dashboard_response = client.get("/runs/dashboard")
    assert default_dashboard_response.status_code == 200
    default_dashboard = default_dashboard_response.json()
    default_run_ids = {item["run_id"] for item in default_dashboard["items"]}
    assert str(run.id) in default_run_ids
    assert str(normal_run.id) in default_run_ids
    assert body["derived_run_id"] not in default_run_ids
    assert sibling_body["derived_run_id"] not in default_run_ids

    default_list_response = client.get("/runs")
    assert default_list_response.status_code == 200
    default_list_run_ids = {item["id"] for item in default_list_response.json()["items"]}
    assert str(run.id) in default_list_run_ids
    assert str(normal_run.id) in default_list_run_ids
    assert body["derived_run_id"] not in default_list_run_ids

    comparison_response = client.get(
        f"/runs/compare?run_ids={body['derived_run_id']},{sibling_body['derived_run_id']}"
    )
    assert comparison_response.status_code == 200
    comparison_runs = comparison_response.json()["runs"]
    assert {item["source"] for item in comparison_runs} == {"sweep_variant_save"}
    assert {item["source_variant_id"] for item in comparison_runs} == {
        "variant-new",
        "variant-sibling",
    }


def test_legacy_linked_standalone_sweep_variant_stays_independently_saveable(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="sweep-promote-legacy-linked@example.com",
    )
    base_config = _strategy_v2_config()
    first_variant_config = {**base_config, "name": "qqq-rsi-sweep-legacy-20"}
    first_variant_config["entry_rule"] = {**base_config["entry_rule"], "threshold": 20}
    sibling_variant_config = {**base_config, "name": "qqq-rsi-sweep-legacy-25"}
    sibling_variant_config["entry_rule"] = {**base_config["entry_rule"], "threshold": 25}

    legacy_strategy, legacy_version = create_strategy_bundle(
        user_id=str(user.id),
        strategy_name="Legacy saved variant",
        config_json=first_variant_config,
    )
    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"base_config": base_config, "grid": {"entry_rule.threshold": [20, 25]}},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": "sharpe_ratio",
            "variant_count": 2,
            "results": [
                {
                    "variant_id": "variant-legacy-saved",
                    "variant_name": first_variant_config["name"],
                    "parameters": {"entry_rule.threshold": 20},
                    "status": "SUCCEEDED",
                    "config": first_variant_config,
                },
                {
                    "variant_id": "variant-legacy-sibling",
                    "variant_name": sibling_variant_config["name"],
                    "parameters": {"entry_rule.threshold": 25},
                    "status": "SUCCEEDED",
                    "config": sibling_variant_config,
                },
            ],
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": "sweep_summary.json"},
    )
    run.strategy_id = legacy_strategy.id
    run.strategy_version_id = legacy_version.id
    db_session.commit()

    detail_response = client.get(f"/runs/{run.id}/sweep/variants/variant-legacy-sibling")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["sweep_origin"] == "STANDALONE"
    assert detail["run"]["strategy_id"] == str(legacy_strategy.id)

    save_response = client.post(
        f"/runs/{run.id}/sweep/variants/variant-legacy-sibling/promote",
        json={"name": "Legacy sibling independent save"},
    )

    assert save_response.status_code == 200
    body = save_response.json()
    assert body["strategy_id"] != str(legacy_strategy.id)


def test_promote_sweep_variant_without_saved_strategy_enforces_strategy_limit(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="sweep-promote-limit@example.com",
        with_default_plan=False,
    )
    plan = create_plan(
        db_session,
        code="ONE_STRATEGY",
        builder_prompt_daily_limit=20,
        builder_prompt_max_chars=1000,
        max_backtest_years=5,
        max_saved_strategies=1,
    )
    attach_plan(db_session, user_id=str(user.id), plan_id=str(plan.id))
    create_strategy_bundle(user_id=str(user.id), strategy_name="Existing saved strategy")

    base_config = _strategy_v2_config()
    variant_config = {**base_config, "name": "qqq-rsi-sweep-limit"}
    variant_config["entry_rule"] = {**base_config["entry_rule"], "threshold": 20}

    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"base_config": base_config, "grid": {"entry_rule.threshold": [20]}},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": "sharpe_ratio",
            "variant_count": 1,
            "results": [
                {
                    "variant_id": "variant-limit",
                    "variant_name": variant_config["name"],
                    "parameters": {"entry_rule.threshold": 20},
                    "status": "SUCCEEDED",
                    "config": variant_config,
                }
            ],
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": "sweep_summary.json"},
    )

    response = client.post(
        f"/runs/{run.id}/sweep/variants/variant-limit/promote",
        json={"name": "Should not save"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Saved strategy limit reached for plan ONE_STRATEGY (1)"


def test_get_sweep_variant_detail_returns_metrics_config_and_rank(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="sweep-variant-detail@example.com",
    )
    base_config = _strategy_v2_config()
    variant_config = {**base_config, "name": "qqq-rsi-sweep-001-threshold-20"}
    variant_config["entry_rule"] = {**base_config["entry_rule"], "threshold": 20}

    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"base_config": base_config, "grid": {"entry_rule.threshold": [20]}},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "run_type": "PARAMETER_SWEEP",
            "ranking_metric": "sharpe_ratio",
            "variant_count": 1,
            "best_variant": {
                "variant_id": "variant-detail",
                "variant_name": variant_config["name"],
                "parameters": {"entry_rule.threshold": 20},
                "status": "SUCCEEDED",
                "total_return_pct": 12.3,
                "config": variant_config,
            },
            "results": [
                {
                    "variant_id": "variant-detail",
                    "variant_name": variant_config["name"],
                    "parameters": {"entry_rule.threshold": 20},
                    "status": "SUCCEEDED",
                    "total_return_pct": 12.3,
                    "config": variant_config,
                }
            ],
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": "sweep_summary.json"},
    )

    response = client.get(f"/runs/{run.id}/sweep/variants/variant-detail")

    assert response.status_code == 200
    body = response.json()
    assert body["rank"] == 1
    assert body["ranking_metric"] == "sharpe_ratio"
    assert body["sweep_origin"] == "STANDALONE"
    assert body["chart_data"] is None
    assert body["variant"]["total_return_pct"] == 12.3
    assert body["variant"]["config"]["entry_rule"]["threshold"] == 20


def test_promote_sweep_variant_missing_variant_returns_friendly_error(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="sweep-promote-missing@example.com",
    )
    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"base_config": _strategy_v2_config(), "grid": {"entry_rule.threshold": [20]}},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)
    mark_run_succeeded(
        db_session,
        run,
        summary_json={"run_type": "PARAMETER_SWEEP", "results": []},
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"sweep_summary": "sweep_summary.json"},
    )

    response = client.post(f"/runs/{run.id}/sweep/variants/does-not-exist/promote", json={})

    assert response.status_code == 404
    assert response.json()["detail"] == "Sweep variant not found"


def test_promote_sweep_variant_non_succeeded_run_returns_friendly_error(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(
        user_id=current_user_ctx["id"],
        email="sweep-promote-pending@example.com",
    )
    run = create_run(
        db_session,
        str(user.id),
        None,
        None,
        "PARAMETER_SWEEP",
        "SWEEP_EXECUTOR",
        {"base_config": _strategy_v2_config(), "grid": {"entry_rule.threshold": [20]}},
        max_attempts=3,
    )

    response = client.post(f"/runs/{run.id}/sweep/variants/variant-new/promote", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "Only succeeded parameter sweep runs can promote variants"


def test_list_runs_returns_paginated_wrapper(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    _create_run_via_api(
        client,
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        request_payload={"note": "list test"},
    )

    response = client.get("/runs")
    assert response.status_code == 200

    body = response.json()
    assert "items" in body
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["has_next"] is False
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "PENDING"
    assert body["items"][0]["strategy_name"] == strategy.name
    assert body["items"][0]["strategy_version_number"] == version.version_number


def test_list_runs_supports_pagination(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    for i in range(3):
        _create_run_via_api(
            client,
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            request_payload={"index": i},
        )

    page_1 = client.get("/runs?page=1&page_size=2")
    assert page_1.status_code == 200
    body_1 = page_1.json()

    assert body_1["total"] == 3
    assert body_1["page"] == 1
    assert body_1["page_size"] == 2
    assert body_1["has_next"] is True
    assert len(body_1["items"]) == 2

    page_2 = client.get("/runs?page=2&page_size=2")
    assert page_2.status_code == 200
    body_2 = page_2.json()

    assert body_2["total"] == 3
    assert body_2["page"] == 2
    assert body_2["page_size"] == 2
    assert body_2["has_next"] is False
    assert len(body_2["items"]) == 1


def test_list_runs_filters_by_status(
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

    pending_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "pending run"},
        max_attempts=3,
    )

    succeeded_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "succeeded run"},
        max_attempts=3,
    )
    succeeded_run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(succeeded_run)

    mark_run_succeeded(
        db_session,
        succeeded_run,
        summary_json={"ok": True},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-run/summary.json"},
    )

    response = client.get("/runs?status=SUCCEEDED")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(succeeded_run.id)
    assert body["items"][0]["status"] == "SUCCEEDED"
    assert body["items"][0]["id"] != str(pending_run.id)


def test_list_runs_filters_by_strategy_id(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    strategy_a, version_a = create_strategy_bundle(user_id=current_user_ctx["id"])
    strategy_b, version_b = create_strategy_bundle(user_id=current_user_ctx["id"])

    _create_run_via_api(
        client,
        strategy_id=str(strategy_a.id),
        strategy_version_id=str(version_a.id),
        request_payload={"strategy": "a"},
    )
    _create_run_via_api(
        client,
        strategy_id=str(strategy_b.id),
        strategy_version_id=str(version_b.id),
        request_payload={"strategy": "b"},
    )

    response = client.get(f"/runs?strategy_id={strategy_a.id}")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["strategy_id"] == str(strategy_a.id)


def test_list_runs_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, version = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = owner_id
    _create_run_via_api(
        client,
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        request_payload={"note": "owner run"},
    )

    current_user_ctx["id"] = other_user_id
    response = client.get("/runs")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 0
    assert body["items"] == []
    assert body["has_next"] is False


def test_list_runs_rejects_invalid_pagination(
    client,
):
    response = client.get("/runs?page=0&page_size=101")
    assert response.status_code == 422


def test_enqueue_then_cancel_run(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "enqueue cancel test"},
            "max_attempts": 3,
        },
    )
    run_id = create_resp.json()["id"]

    enqueue_resp = client.post(f"/runs/{run_id}/enqueue")
    assert enqueue_resp.status_code == 200
    assert enqueue_resp.json()["status"] == "QUEUED"

    cancel_resp = client.post(f"/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELED"

    get_resp = client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "CANCELED"
    assert get_resp.json()["progress_message"] == "Run canceled by user request"


def test_cannot_enqueue_canceled_run(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "guardrail test"},
            "max_attempts": 3,
        },
    )
    run_id = create_resp.json()["id"]

    assert client.post(f"/runs/{run_id}/cancel").status_code == 200

    enqueue_resp = client.post(f"/runs/{run_id}/enqueue")
    assert enqueue_resp.status_code == 400
    assert "cannot be enqueued" in enqueue_resp.json()["detail"].lower()


def test_cannot_cancel_succeeded_run(
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
        {"note": "succeeded run"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"ok": True},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-run/summary.json"},
    )

    cancel_resp = client.post(f"/runs/{run.id}/cancel")
    assert cancel_resp.status_code == 400
    assert "cannot be canceled" in cancel_resp.json()["detail"].lower()


def test_get_run_enforces_ownership(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    owner_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    create_user(user_id=owner_id, email="owner@example.com")
    create_user(user_id=other_user_id, email="other@example.com")

    strategy, version = create_strategy_bundle(user_id=owner_id)

    current_user_ctx["id"] = owner_id
    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "ownership test"},
            "max_attempts": 3,
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    current_user_ctx["id"] = other_user_id
    get_resp = client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 404

    enqueue_resp = client.post(f"/runs/{run_id}/enqueue")
    assert enqueue_resp.status_code == 400
    assert "not found" in enqueue_resp.json()["detail"].lower()


def test_compare_runs_chart_returns_normalized_strategy_benchmark_and_drawdown_curves(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    run_1 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "compare chart 1", "benchmark_symbol": "QQQ"},
        max_attempts=3,
    )
    run_1.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run_1)

    mark_run_succeeded(
        db_session,
        run_1,
        summary_json={"total_return_pct": 10.0},
        artifact_dir="data/local_artifacts/runs/test-compare-1",
        artifact_manifest_json={"summary": "dummy-1"},
    )

    run_2 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "compare chart 2", "draft_config": {"benchmark_symbol": "SPY"}},
        max_attempts=3,
    )
    run_2.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run_2)

    mark_run_succeeded(
        db_session,
        run_2,
        summary_json={"total_return_pct": 20.0},
        artifact_dir="data/local_artifacts/runs/test-compare-2",
        artifact_manifest_json={"summary": "dummy-2"},
    )

    def fake_load_chart_data(manifest):
        summary_ref = manifest["summary"]

        if summary_ref == "dummy-1":
            return {
                "equity_curve": [
                    {"date": "2024-01-01", "strategy_equity": 100000.0, "benchmark_equity": 100000.0},
                    {"date": "2024-01-02", "strategy_equity": 110000.0, "benchmark_equity": 105000.0},
                ],
                "drawdown_curve": [
                    {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                    {"date": "2024-01-02", "strategy_drawdown_pct": -2.0, "benchmark_drawdown_pct": -1.0},
                ],
                "monthly_returns": [],
                "sleeve_equity_curve": [],
                "sleeve_weight_curve": [],
                "trade_markers": [],
            }

        return {
            "equity_curve": [
                {"date": "2024-01-01", "strategy_equity": 200000.0, "benchmark_equity": 200000.0},
                {"date": "2024-01-02", "strategy_equity": 220000.0, "benchmark_equity": 210000.0},
            ],
            "drawdown_curve": [
                {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-01-02", "strategy_drawdown_pct": -3.0, "benchmark_drawdown_pct": -1.5},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    response = client.get(f"/runs/compare/chart?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()

    assert "strategy_curves" in body
    assert "benchmark_curves" in body
    assert "strategy_drawdown_curves" in body
    assert "benchmark_drawdown_curves" in body

    assert len(body["strategy_curves"]) == 2
    assert len(body["benchmark_curves"]) == 2
    assert len(body["strategy_drawdown_curves"]) == 2
    assert len(body["benchmark_drawdown_curves"]) == 2

    assert body["strategy_curves"][0]["label"] is not None
    assert body["benchmark_curves"][0]["label"] is not None
    assert body["strategy_drawdown_curves"][0]["label"] is not None
    assert body["benchmark_drawdown_curves"][0]["label"] is not None
    assert body["strategy_curves"][0]["benchmark_label"] is None
    assert body["benchmark_curves"][0]["benchmark_label"] == "QQQ"
    assert body["benchmark_curves"][1]["benchmark_label"] == "SPY"
    assert body["benchmark_curves"][0]["label"].startswith("QQQ · ")
    assert body["benchmark_drawdown_curves"][1]["label"].startswith("SPY · ")

    assert body["strategy_curves"][0]["points"][0]["value"] == 100.0
    assert body["strategy_curves"][0]["points"][1]["value"] == 110.0
    assert body["benchmark_curves"][0]["points"][0]["value"] == 100.0
    assert body["benchmark_curves"][0]["points"][1]["value"] == 105.0

    assert body["strategy_curves"][1]["points"][0]["value"] == 100.0
    assert body["strategy_curves"][1]["points"][1]["value"] == 110.0
    assert body["benchmark_curves"][1]["points"][0]["value"] == 100.0
    assert body["benchmark_curves"][1]["points"][1]["value"] == 105.0

    assert body["strategy_drawdown_curves"][0]["points"][1]["value"] == -2.0
    assert body["benchmark_drawdown_curves"][0]["points"][1]["value"] == -1.0
    assert body["strategy_drawdown_curves"][1]["points"][1]["value"] == -3.0
    assert body["benchmark_drawdown_curves"][1]["points"][1]["value"] == -1.5


def test_compare_runs_chart_skips_unreadable_run_artifacts(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_with_chart = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="compare chart readable artifact",
    )
    run_missing_chart = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="compare chart missing artifact",
    )

    def fake_load_chart_data(manifest):
        if manifest["summary"] == f"dummy-{run_missing_chart.id}":
            raise FileNotFoundError("missing timeline.csv")

        return {
            "equity_curve": [
                {"date": "2024-01-01", "strategy_equity": 100000.0, "benchmark_equity": 100000.0},
                {"date": "2024-01-02", "strategy_equity": 105000.0, "benchmark_equity": 102000.0},
            ],
            "drawdown_curve": [
                {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-01-02", "strategy_drawdown_pct": -1.0, "benchmark_drawdown_pct": -0.5},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    response = client.get(f"/runs/compare/chart?run_ids={run_with_chart.id},{run_missing_chart.id}")

    assert response.status_code == 200
    body = response.json()
    assert [curve["run_id"] for curve in body["strategy_curves"]] == [str(run_with_chart.id)]
    assert [curve["run_id"] for curve in body["benchmark_curves"]] == [str(run_with_chart.id)]


def test_compare_runs_returns_strategy_metadata(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
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
        {"note": "compare summary metadata"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-compare-summary",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-compare-summary/summary.json"},
    )

    run_2 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "compare summary metadata 2"},
        max_attempts=3,
    )
    run_2.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run_2)

    mark_run_succeeded(
        db_session,
        run_2,
        summary_json={"total_return_pct": 15.6},
        artifact_dir="data/local_artifacts/runs/test-compare-summary-2",
        artifact_manifest_json={"summary": "data/local_artifacts/runs/test-compare-summary-2/summary.json"},
    )

    response = client.get(f"/runs/compare?run_ids={run.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()
    assert len(body["runs"]) == 2

    target_run = next(item for item in body["runs"] if item["run_id"] == str(run.id))

    assert target_run["strategy_id"] == str(strategy.id)
    assert target_run["strategy_version_id"] == str(version.id)
    assert target_run["strategy_name"] == strategy.name
    assert target_run["strategy_version_number"] == version.version_number


def test_runs_dashboard_exposes_sweep_variants_as_comparable_children(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    create_user(user_id=current_user_ctx["id"], email="compare-sweep-list@example.com")
    sweep_run = _create_succeeded_sweep_with_variants(
        db_session,
        user_id=current_user_ctx["id"],
    )

    response = client.get("/runs/dashboard?status=SUCCEEDED")
    assert response.status_code == 200

    body = response.json()
    sweep_item = next(item for item in body["items"] if item["run_id"] == str(sweep_run.id))
    assert sweep_item["result_type"] == "PARAMETER_SWEEP_GROUP"
    assert sweep_item["comparable_result_ref"] is None
    assert sweep_item["sweep_variant_count"] == 2
    assert [variant["variant_id"] for variant in sweep_item["sweep_variants"]] == [
        "variant-a",
        "variant-b",
    ]
    assert sweep_item["sweep_variants"][0]["comparable_result_ref"] == (
        f"sweep_variant:{sweep_run.id}:variant-a"
    )
    assert "Rank #1" in sweep_item["sweep_variants"][0]["label"]


def test_compare_normal_run_and_sweep_variant_with_typed_results(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="compare-normal-variant@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    normal_run = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="compare normal plus variant",
    )
    sweep_run = _create_succeeded_sweep_with_variants(
        db_session,
        user_id=current_user_ctx["id"],
    )
    _mock_comparable_chart_data(monkeypatch)

    results = f"run:{normal_run.id},sweep_variant:{sweep_run.id}:variant-a"
    response = client.get(f"/runs/compare?results={results}")
    assert response.status_code == 200

    body = response.json()
    assert [item["result_ref"] for item in body["runs"]] == [
        f"run:{normal_run.id}",
        f"sweep_variant:{sweep_run.id}:variant-a",
    ]
    variant_summary = body["runs"][1]
    assert variant_summary["result_type"] == "SWEEP_VARIANT"
    assert variant_summary["source"] == "sweep_variant"
    assert variant_summary["source_sweep_run_id"] == str(sweep_run.id)
    assert variant_summary["source_variant_id"] == "variant-a"
    assert variant_summary["source_variant_rank"] == 1
    assert variant_summary["total_return_pct"] == 12.5
    assert "Rank #1" in variant_summary["label"]

    chart_response = client.get(f"/runs/compare/chart?results={results}")
    assert chart_response.status_code == 200
    chart_body = chart_response.json()
    assert [curve["result_ref"] for curve in chart_body["strategy_curves"]] == [
        f"run:{normal_run.id}",
        f"sweep_variant:{sweep_run.id}:variant-a",
    ]
    assert chart_body["strategy_curves"][1]["points"][1]["value"] == 112.5


def test_compare_sweep_variant_against_sweep_variant_with_typed_results(
    client,
    db_session,
    create_user,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="compare-variant-variant@example.com")
    sweep_run = _create_succeeded_sweep_with_variants(
        db_session,
        user_id=current_user_ctx["id"],
    )
    _mock_comparable_chart_data(monkeypatch)

    results = f"sweep_variant:{sweep_run.id}:variant-a,sweep_variant:{sweep_run.id}:variant-b"
    response = client.get(f"/runs/compare?results={results}")
    assert response.status_code == 200
    assert [item["source_variant_id"] for item in response.json()["runs"]] == [
        "variant-a",
        "variant-b",
    ]

    chart_response = client.get(f"/runs/compare/chart?results={results}")
    assert chart_response.status_code == 200
    chart_body = chart_response.json()
    assert [curve["run_id"] for curve in chart_body["strategy_curves"]] == [
        f"sweep_variant:{sweep_run.id}:variant-a",
        f"sweep_variant:{sweep_run.id}:variant-b",
    ]
    assert chart_body["strategy_curves"][0]["points"][1]["value"] == 112.5
    assert chart_body["strategy_curves"][1]["points"][1]["value"] == 109.5


def test_compare_rejects_parameter_sweep_parent_result(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(user_id=current_user_ctx["id"], email="compare-parent-reject@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    normal_run = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="compare parent reject normal",
    )
    sweep_run = _create_succeeded_sweep_with_variants(
        db_session,
        user_id=current_user_ctx["id"],
    )

    response = client.get(f"/runs/compare?results=run:{normal_run.id},run:{sweep_run.id}")

    assert response.status_code == 400
    assert "Parameter sweep parent results cannot be compared directly" in response.json()["detail"]


def test_compare_invalid_sweep_variant_returns_clear_404(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(user_id=current_user_ctx["id"], email="compare-invalid-variant@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    normal_run = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="compare invalid variant normal",
    )
    sweep_run = _create_succeeded_sweep_with_variants(
        db_session,
        user_id=current_user_ctx["id"],
    )

    response = client.get(
        f"/runs/compare?results=run:{normal_run.id},sweep_variant:{sweep_run.id}:missing-variant"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Sweep variant not found: missing-variant"


def test_compare_limit_counts_sweep_variants(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="compare-variant-limit@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    runs = [
        _create_succeeded_run(
            db_session,
            user_id=current_user_ctx["id"],
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            note=f"compare variant limit {index}",
        )
        for index in range(3)
    ]
    sweep_run = _create_succeeded_sweep_with_variants(
        db_session,
        user_id=current_user_ctx["id"],
    )

    def fail_if_compared(_runs):
        raise AssertionError("over-limit mixed comparison should be rejected before building comparison")

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.build_comparison",
        fail_if_compared,
    )

    results = ",".join(
        [
            *(f"run:{run.id}" for run in runs),
            f"sweep_variant:{sweep_run.id}:variant-a",
            f"sweep_variant:{sweep_run.id}:variant-b",
        ]
    )
    response = client.get(f"/runs/compare?results={results}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Comparison limit reached for your plan. Select up to 4 runs."


def test_compare_runs_metadata_same_date_windows_has_common_overlap(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="owner@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_1 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="same window 1",
    )
    run_2 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="same window 2",
    )
    run_1.summary_json = {
        "total_return_pct": 42.0,
        "trade_count": 12,
        "win_rate_pct": 55.5,
    }
    db_session.commit()
    _mock_compare_chart_windows(
        monkeypatch,
        {
            f"dummy-{run_1.id}": ("2024-01-01", "2024-12-31"),
            f"dummy-{run_2.id}": ("2024-01-01", "2024-12-31"),
        },
    )

    response = client.get(f"/runs/compare?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    metadata = response.json()["metadata"]
    assert metadata["run_windows"] == [
        {
            "run_id": str(run_1.id),
            "result_ref": f"run:{run_1.id}",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
        {
            "run_id": str(run_2.id),
            "result_ref": f"run:{run_2.id}",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    ]
    assert metadata["overlap_start"] == "2024-01-01"
    assert metadata["overlap_end"] == "2024-12-31"
    assert metadata["has_common_overlap"] is True
    assert metadata["window_mode"] == "FULL_PERIOD_METRICS"
    assert metadata["warning_message"] is None

    target_run = next(item for item in response.json()["runs"] if item["run_id"] == str(run_1.id))
    assert target_run["total_return_pct"] == 42.0
    assert target_run["trade_count"] == 12
    assert target_run["win_rate_pct"] == 55.5


def test_compare_runs_metadata_different_overlapping_windows_uses_overlap_metrics(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="owner@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_1 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="overlap window 1",
    )
    run_2 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="overlap window 2",
    )
    run_1.summary_json = {
        "total_return_pct": 999.0,
        "benchmark_return_pct": 777.0,
        "alpha_vs_benchmark_pct": 222.0,
        "trade_count": 10,
        "win_rate_pct": 70.0,
    }
    run_2.summary_json = {
        "total_return_pct": 888.0,
        "benchmark_return_pct": 666.0,
        "alpha_vs_benchmark_pct": 222.0,
        "trade_count": 20,
        "win_rate_pct": 80.0,
    }
    db_session.commit()

    chart_data_by_summary = {
        f"dummy-{run_1.id}": {
            "equity_curve": [
                {"date": "2023-01-01", "strategy_equity": 100.0, "benchmark_equity": 100.0},
                {"date": "2024-03-01", "strategy_equity": 120.0, "benchmark_equity": 110.0},
                {"date": "2024-06-01", "strategy_equity": 150.0, "benchmark_equity": 121.0},
                {"date": "2024-12-31", "strategy_equity": 180.0, "benchmark_equity": 132.0},
            ],
            "drawdown_curve": [
                {"date": "2023-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-03-01", "strategy_drawdown_pct": -4.0, "benchmark_drawdown_pct": -2.0},
                {"date": "2024-06-01", "strategy_drawdown_pct": -3.0, "benchmark_drawdown_pct": -1.0},
                {"date": "2024-12-31", "strategy_drawdown_pct": -6.0, "benchmark_drawdown_pct": -3.0},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        },
        f"dummy-{run_2.id}": {
            "equity_curve": [
                {"date": "2024-03-01", "strategy_equity": 200.0, "benchmark_equity": 300.0},
                {"date": "2024-06-01", "strategy_equity": 220.0, "benchmark_equity": 330.0},
                {"date": "2025-02-28", "strategy_equity": 260.0, "benchmark_equity": 360.0},
            ],
            "drawdown_curve": [
                {"date": "2024-03-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-06-01", "strategy_drawdown_pct": -1.0, "benchmark_drawdown_pct": -0.5},
                {"date": "2025-02-28", "strategy_drawdown_pct": -2.0, "benchmark_drawdown_pct": -1.0},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        },
    }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        lambda manifest: chart_data_by_summary[manifest["summary"]],
    )

    response = client.get(f"/runs/compare?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()
    metadata = body["metadata"]
    assert metadata["overlap_start"] == "2024-03-01"
    assert metadata["overlap_end"] == "2024-12-31"
    assert metadata["has_common_overlap"] is True
    assert metadata["window_mode"] == "COMMON_OVERLAP_METRICS"
    assert metadata["warning_message"] is None

    run_1_summary = next(item for item in body["runs"] if item["run_id"] == str(run_1.id))
    assert run_1_summary["total_return_pct"] == 50.0
    assert run_1_summary["benchmark_return_pct"] == 20.0
    assert run_1_summary["alpha_vs_benchmark_pct"] == 30.0
    assert run_1_summary["max_drawdown_pct"] == -6.0
    assert run_1_summary["benchmark_max_drawdown_pct"] == -3.0
    assert run_1_summary["trade_count"] is None
    assert run_1_summary["win_rate_pct"] is None

    run_2_summary = next(item for item in body["runs"] if item["run_id"] == str(run_2.id))
    assert run_2_summary["total_return_pct"] == 10.0
    assert run_2_summary["benchmark_return_pct"] == 10.0
    assert run_2_summary["alpha_vs_benchmark_pct"] == 0.0


def test_compare_runs_metadata_non_overlapping_windows_warns(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="owner@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_1 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="non-overlap window 1",
    )
    run_2 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="non-overlap window 2",
    )
    _mock_compare_chart_windows(
        monkeypatch,
        {
            f"dummy-{run_1.id}": ("2022-01-01", "2022-12-31"),
            f"dummy-{run_2.id}": ("2024-01-01", "2024-12-31"),
        },
    )

    response = client.get(f"/runs/compare?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    metadata = response.json()["metadata"]
    assert metadata["overlap_start"] == "2024-01-01"
    assert metadata["overlap_end"] == "2022-12-31"
    assert metadata["has_common_overlap"] is False
    assert metadata["window_mode"] == "FULL_PERIOD_METRICS"
    assert "common comparison window" in metadata["warning_message"].lower()


def test_compare_runs_chart_same_date_windows_uses_full_period(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="owner@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_1 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="same chart window 1",
    )
    run_2 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="same chart window 2",
    )

    def fake_load_chart_data(manifest):
        return {
            "equity_curve": [
                {"date": "2024-01-01", "strategy_equity": 100.0, "benchmark_equity": 200.0},
                {"date": "2024-06-01", "strategy_equity": 110.0, "benchmark_equity": 210.0},
                {"date": "2024-12-31", "strategy_equity": 125.0, "benchmark_equity": 220.0},
            ],
            "drawdown_curve": [
                {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-06-01", "strategy_drawdown_pct": -2.0, "benchmark_drawdown_pct": -1.0},
                {"date": "2024-12-31", "strategy_drawdown_pct": -3.0, "benchmark_drawdown_pct": -1.5},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    response = client.get(f"/runs/compare/chart?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()
    assert body["chart_window_mode"] == "FULL_PERIOD"
    assert body["chart_overlap_start"] == "2024-01-01"
    assert body["chart_overlap_end"] == "2024-12-31"

    curve = next(item for item in body["strategy_curves"] if item["run_id"] == str(run_1.id))
    assert curve["points"] == [
        {"date": "2024-01-01", "value": 100.0},
        {"date": "2024-06-01", "value": 110.0},
        {"date": "2024-12-31", "value": 125.0},
    ]


def test_compare_runs_chart_overlapping_different_windows_clips_and_normalizes(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="owner@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_1 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="overlap chart window 1",
    )
    run_2 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="overlap chart window 2",
    )

    chart_data_by_summary = {
        f"dummy-{run_1.id}": {
            "equity_curve": [
                {"date": "2023-01-01", "strategy_equity": 100.0, "benchmark_equity": 100.0},
                {"date": "2024-03-01", "strategy_equity": 120.0, "benchmark_equity": 110.0},
                {"date": "2024-12-31", "strategy_equity": 180.0, "benchmark_equity": 132.0},
            ],
            "drawdown_curve": [
                {"date": "2023-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-03-01", "strategy_drawdown_pct": -4.0, "benchmark_drawdown_pct": -2.0},
                {"date": "2024-12-31", "strategy_drawdown_pct": -6.0, "benchmark_drawdown_pct": -3.0},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        },
        f"dummy-{run_2.id}": {
            "equity_curve": [
                {"date": "2024-03-01", "strategy_equity": 200.0, "benchmark_equity": 300.0},
                {"date": "2024-06-01", "strategy_equity": 220.0, "benchmark_equity": 315.0},
                {"date": "2025-02-28", "strategy_equity": 260.0, "benchmark_equity": 330.0},
            ],
            "drawdown_curve": [
                {"date": "2024-03-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-06-01", "strategy_drawdown_pct": -1.0, "benchmark_drawdown_pct": -0.5},
                {"date": "2025-02-28", "strategy_drawdown_pct": -2.0, "benchmark_drawdown_pct": -1.0},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        },
    }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        lambda manifest: chart_data_by_summary[manifest["summary"]],
    )

    response = client.get(f"/runs/compare/chart?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()
    assert body["chart_window_mode"] == "COMMON_OVERLAP"
    assert body["chart_overlap_start"] == "2024-03-01"
    assert body["chart_overlap_end"] == "2024-12-31"

    run_1_strategy_curve = next(item for item in body["strategy_curves"] if item["run_id"] == str(run_1.id))
    run_2_strategy_curve = next(item for item in body["strategy_curves"] if item["run_id"] == str(run_2.id))
    run_1_benchmark_curve = next(item for item in body["benchmark_curves"] if item["run_id"] == str(run_1.id))
    run_2_drawdown_curve = next(item for item in body["strategy_drawdown_curves"] if item["run_id"] == str(run_2.id))

    assert run_1_strategy_curve["points"] == [
        {"date": "2024-03-01", "value": 100.0},
        {"date": "2024-12-31", "value": 150.0},
    ]
    assert run_2_strategy_curve["points"] == [
        {"date": "2024-03-01", "value": 100.0},
        {"date": "2024-06-01", "value": 110.0},
    ]
    assert run_1_benchmark_curve["points"] == [
        {"date": "2024-03-01", "value": 100.0},
        {"date": "2024-12-31", "value": 120.0},
    ]
    assert run_2_drawdown_curve["points"] == [
        {"date": "2024-03-01", "value": 0.0},
        {"date": "2024-06-01", "value": -1.0},
    ]


def test_compare_runs_chart_non_overlapping_windows_does_not_crash(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(user_id=current_user_ctx["id"], email="owner@example.com")
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    run_1 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="non-overlap chart window 1",
    )
    run_2 = _create_succeeded_run(
        db_session,
        user_id=current_user_ctx["id"],
        strategy_id=str(strategy.id),
        strategy_version_id=str(version.id),
        note="non-overlap chart window 2",
    )
    _mock_compare_chart_windows(
        monkeypatch,
        {
            f"dummy-{run_1.id}": ("2022-01-01", "2022-12-31"),
            f"dummy-{run_2.id}": ("2024-01-01", "2024-12-31"),
        },
    )

    response = client.get(f"/runs/compare/chart?run_ids={run_1.id},{run_2.id}")
    assert response.status_code == 200

    body = response.json()
    assert body["chart_window_mode"] == "FULL_PERIOD"
    assert body["chart_overlap_start"] is None
    assert body["chart_overlap_end"] is None
    assert len(body["strategy_curves"]) == 2


def test_compare_runs_rejects_more_than_max_comparison_runs(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    runs = [
        _create_succeeded_run(
            db_session,
            user_id=current_user_ctx["id"],
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            note=f"compare limit {index}",
        )
        for index in range(5)
    ]

    def fail_if_compared(_runs):
        raise AssertionError("over-limit comparison should be rejected before building comparison")

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.build_comparison",
        fail_if_compared,
    )

    run_ids = ",".join(str(run.id) for run in runs)
    response = client.get(f"/runs/compare?run_ids={run_ids}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Comparison limit reached for your plan. Select up to 4 runs."


def test_compare_runs_chart_rejects_more_than_max_comparison_runs(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    runs = [
        _create_succeeded_run(
            db_session,
            user_id=current_user_ctx["id"],
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            note=f"compare chart limit {index}",
        )
        for index in range(5)
    ]

    def fail_if_compared(_runs):
        raise AssertionError("over-limit chart comparison should be rejected before building curves")

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.build_equity_curves",
        fail_if_compared,
    )

    run_ids = ",".join(str(run.id) for run in runs)
    response = client.get(f"/runs/compare/chart?run_ids={run_ids}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Comparison limit reached for your plan. Select up to 4 runs."


def test_compare_runs_allows_exactly_max_comparison_runs(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])
    runs = [
        _create_succeeded_run(
            db_session,
            user_id=current_user_ctx["id"],
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            note=f"compare max {index}",
        )
        for index in range(4)
    ]

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.comparison_service.chart_service.load_chart_data",
        lambda manifest: {
            "equity_curve": [
                {"date": "2024-01-01", "strategy_equity": 100000.0, "benchmark_equity": 100000.0},
                {"date": "2024-01-02", "strategy_equity": 101000.0, "benchmark_equity": 100500.0},
            ],
            "drawdown_curve": [
                {"date": "2024-01-01", "strategy_drawdown_pct": 0.0, "benchmark_drawdown_pct": 0.0},
                {"date": "2024-01-02", "strategy_drawdown_pct": -1.0, "benchmark_drawdown_pct": -0.5},
            ],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        },
    )

    run_ids = ",".join(str(run.id) for run in runs)

    compare_response = client.get(f"/runs/compare?run_ids={run_ids}")
    assert compare_response.status_code == 200
    assert len(compare_response.json()["runs"]) == 4

    chart_response = client.get(f"/runs/compare/chart?run_ids={run_ids}")
    assert chart_response.status_code == 200
    assert len(chart_response.json()["strategy_curves"]) == 4


def test_compare_runs_requires_at_least_two_runs(client):
    response = client.get("/runs/compare?run_ids=00000000-0000-0000-0000-000000000001")

    assert response.status_code == 400
    assert "at least two run ids are required" in response.json()["detail"].lower()


def test_get_run_returns_strategy_metadata(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )
    strategy, version = create_strategy_bundle(user_id=current_user_ctx["id"])

    create_resp = client.post(
        "/runs",
        json={
            "strategy_id": str(strategy.id),
            "strategy_version_id": str(version.id),
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {"note": "get run metadata test"},
            "max_attempts": 3,
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["id"] == run_id
    assert body["strategy_id"] == str(strategy.id)
    assert body["strategy_version_id"] == str(version.id)
    assert body["strategy_name"] == strategy.name
    assert body["strategy_version_number"] == version.version_number


def test_get_run_dashboard_returns_nested_run_strategy_metadata(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
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
        {"note": "dashboard metadata"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-dashboard-metadata",
        artifact_manifest_json={"summary": "dummy"},
    )

    def fake_load_chart_data(_):
        return {
            "equity_curve": [],
            "drawdown_curve": [],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    response = client.get(f"/runs/{run.id}/dashboard")
    assert response.status_code == 200

    body = response.json()
    assert body["run"]["id"] == str(run.id)
    assert body["run"]["strategy_id"] == str(strategy.id)
    assert body["run"]["strategy_version_id"] == str(version.id)
    assert body["run"]["strategy_name"] == strategy.name
    assert body["run"]["strategy_version_number"] == version.version_number


def test_get_run_chart_data_preserves_trade_marker_actions(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    monkeypatch,
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
        {"note": "trade marker labels"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-trade-markers",
        artifact_manifest_json={"summary": "dummy"},
    )

    def fake_load_chart_data(_):
        return {
            "equity_curve": [],
            "drawdown_curve": [],
            "monthly_returns": [],
            "sleeve_equity_curve": [],
            "sleeve_weight_curve": [],
            "trade_markers": [
                {
                    "date": "2024-01-02",
                    "side": "BUY",
                    "shares": 100.0,
                    "price": 100.0,
                    "reason": None,
                },
                {
                    "date": "2024-01-10",
                    "side": "BUY_ADD",
                    "shares": 25.0,
                    "price": 102.0,
                    "reason": None,
                },
                {
                    "date": "2024-01-15",
                    "side": "SELL_REDUCE",
                    "shares": 50.0,
                    "price": 105.0,
                    "reason": "exit_signal",
                },
                {
                    "date": "2024-01-20",
                    "side": "SELL_ALL",
                    "shares": 75.0,
                    "price": 107.0,
                    "reason": "exit_signal",
                },
            ],
        }

    monkeypatch.setattr(
        "market_simulator.api.routers.runs.chart_service.load_chart_data",
        fake_load_chart_data,
    )

    response = client.get(f"/runs/{run.id}/chart-data")
    assert response.status_code == 200

    body = response.json()
    assert body["run_id"] == str(run.id)

    markers = body["trade_markers"]
    assert [marker["side"] for marker in markers] == [
        "BUY",
        "BUY_ADD",
        "SELL_REDUCE",
        "SELL_ALL",
    ]
    assert markers[0]["shares"] == 100.0
    assert markers[1]["shares"] == 25.0
    assert markers[2]["reason"] == "exit_signal"
    assert markers[3]["price"] == 107.0


def test_compare_runs_chart_requires_at_least_two_runs(
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
        {"note": "single compare chart run"},
        max_attempts=3,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 10.0},
        artifact_dir="data/local_artifacts/runs/test-single-compare-chart",
        artifact_manifest_json={"summary": "dummy"},
    )

    response = client.get(f"/runs/compare/chart?run_ids={run.id}")
    assert response.status_code == 400
    assert "at least two run ids are required" in response.json()["detail"].lower()


def test_runs_dashboard_supports_filter_and_sort(
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

    strategy_a, version_a = create_strategy_bundle(user_id=current_user_ctx["id"])
    strategy_b, version_b = create_strategy_bundle(user_id=current_user_ctx["id"])

    run_1 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy_a.id),
        str(version_a.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "dashboard test 1"},
        max_attempts=3,
    )
    run_1.status = RunStatus.SUCCEEDED

    run_2 = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy_b.id),
        str(version_b.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "dashboard test 2"},
        max_attempts=3,
    )
    run_2.status = RunStatus.FAILED

    db_session.commit()

    response = client.get(
        f"/runs/dashboard?status=SUCCEEDED&strategy_id={strategy_a.id}&sort_by=created_at&sort_order=desc"
    )
    assert response.status_code == 200

    body = response.json()

    assert body["total"] == 1
    assert len(body["items"]) == 1

    item = body["items"][0]

    assert item["run_id"] == str(run_1.id)
    assert item["strategy_id"] == str(strategy_a.id)
    assert item["status"] == "SUCCEEDED"


def test_runs_dashboard_supports_multi_status_filter(
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

    pending_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "pending"},
        max_attempts=3,
    )

    running_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "running"},
        max_attempts=3,
    )
    running_run.status = RunStatus.RUNNING

    succeeded_run = create_run(
        db_session,
        current_user_ctx["id"],
        str(strategy.id),
        str(version.id),
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": "succeeded"},
        max_attempts=3,
    )
    succeeded_run.status = RunStatus.SUCCEEDED

    db_session.commit()

    response = client.get("/runs/dashboard?status=PENDING&status=RUNNING&sort_by=created_at")
    assert response.status_code == 200

    body = response.json()
    run_ids = {item["run_id"] for item in body["items"]}

    assert body["total"] == 2
    assert run_ids == {str(pending_run.id), str(running_run.id)}
    assert str(succeeded_run.id) not in run_ids


def test_runs_dashboard_invalid_pagination_returns_422(client):
    response = client.get("/runs/dashboard?page=0&page_size=101")
    assert response.status_code == 422


def test_create_draft_run_without_saved_strategy_returns_pending(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "draft-run",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "PENDING"
    assert body["strategy_id"] is None
    assert body["strategy_version_id"] is None
    assert body["strategy_name"] is None
    assert body["request_payload"]["draft_config"]["tradable_symbol"] == "QQQ"


def test_save_draft_run_as_strategy_creates_strategy_and_links_run(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    create_resp = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "draft-run",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    run = get_run(db_session, run_id)
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 12.3},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary_json": "summary.json"},
    )

    save_resp = client.post(
        f"/runs/{run_id}/save-strategy",
        json={
            "name": "My Saved Draft",
            "description": "Saved from run detail",
            "strategy_type": "SINGLE_ASSET",
        },
    )
    assert save_resp.status_code == 200

    body = save_resp.json()
    assert body["run_id"] == run_id
    assert body["strategy_id"] is not None
    assert body["version_id"] is not None

    get_resp = client.get(f"/runs/{run_id}")
    assert get_resp.status_code == 200
    get_body = get_resp.json()

    assert get_body["strategy_id"] == body["strategy_id"]
    assert get_body["strategy_version_id"] == body["version_id"]
    assert get_body["strategy_name"] == "My Saved Draft"
    assert get_body["source"] is None

    dashboard_resp = client.get(f"/strategies/{body['strategy_id']}/dashboard")
    assert dashboard_resp.status_code == 200
    dashboard = dashboard_resp.json()
    assert dashboard["versions"][0]["id"] == body["version_id"]
    assert dashboard["versions"][0]["reference_run_id"] == run_id
    assert dashboard["reference_run_id"] == run_id
    assert dashboard["reference_performance"]["run_id"] == run_id
    assert dashboard["reference_performance"]["total_return_pct"] == 12.3


def test_save_draft_run_as_strategy_requires_succeeded_run(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="runs-test@example.com",
    )

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "draft-run",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 200
    run_id = response.json()["id"]

    save_response = client.post(
        f"/runs/{run_id}/save-strategy",
        json={"name": "Saved too early"},
    )

    assert save_response.status_code == 400
    assert "Only succeeded unsaved runs can be saved as a strategy" in save_response.json()["detail"]


def test_create_run_rejects_draft_config_outside_plan_limit(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    plan = db_session.query(Plan).filter(Plan.code == "TEST_PRO").one()
    plan.max_backtest_years = 5
    db_session.commit()
    db_session.refresh(plan)

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "too-long-window",
                "tradable_symbol": "QQQ",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2020-01-02",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "QQQ",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 400
    assert "current plan limit" in response.json()["detail"]
    assert "shorten the range" in response.json()["detail"]


def test_create_run_rejects_draft_config_with_unsupported_symbol(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    response = client.post(
        "/runs",
        json={
            "draft_config": {
                "schema_version": "2.0",
                "name": "unsupported-symbol",
                "tradable_symbol": "AAPL",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            },
            "run_type": "SIMULATION",
            "executor_type": "SIMULATION_EXECUTOR",
            "request_payload": {},
            "max_attempts": 1,
        },
    )

    assert response.status_code == 400
    assert "not supported yet" in response.json()["detail"]
    assert "ETF-first" in response.json()["detail"]


def test_create_run_rejects_duplicate_active_draft_run(
    client,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    payload = {
        "draft_config": {
            "schema_version": "2.0",
            "name": "duplicate-check",
            "tradable_symbol": "QQQ",
            "benchmark_symbol": "QQQ",
            "reference_symbols": [],
            "start_date": "2021-04-14",
            "end_date": "2026-04-14",
            "initial_capital": 100000,
            "transaction_cost_bps": 5,
            "allocation": {
                "entry_mode": "percent_of_equity",
                "entry_value": 1.0,
                "max_position_pct": 1.0,
            },
            "entry_rule": {
                "kind": "atomic",
                "type": "rsi_below",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 30,
            },
            "exit_rule": {
                "kind": "atomic",
                "type": "rsi_above",
                "symbol": "QQQ",
                "lookback": 14,
                "threshold": 70,
            },
            "risk": {"cooldown_bars": 0},
            "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
        },
        "run_type": "SIMULATION",
        "executor_type": "SIMULATION_EXECUTOR",
        "request_payload": {},
        "max_attempts": 1,
    }

    first = client.post("/runs", json=payload)
    assert first.status_code == 200

    second = client.post("/runs", json=payload)
    assert second.status_code == 409

    detail = second.json()["detail"]
    assert detail["code"] == "DUPLICATE_ACTIVE_RUN"
    assert detail["message"] == "An equivalent run is already active."
    assert isinstance(detail["existing_run_id"], str)
    assert detail["existing_run_id"] == first.json()["id"]


def test_save_draft_run_as_strategy_revalidates_draft_config(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    create_user(
        user_id=current_user_ctx["id"],
        email="owner@example.com",
    )

    run = create_run(
        db_session,
        current_user_ctx["id"],
        None,
        None,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {
            "draft_config": {
                "schema_version": "2.0",
                "name": "bad-save",
                "tradable_symbol": "AAPL",
                "benchmark_symbol": "QQQ",
                "reference_symbols": [],
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "initial_capital": 100000,
                "transaction_cost_bps": 5,
                "allocation": {
                    "entry_mode": "percent_of_equity",
                    "entry_value": 1.0,
                    "max_position_pct": 1.0,
                },
                "entry_rule": {
                    "kind": "atomic",
                    "type": "rsi_below",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 30,
                },
                "exit_rule": {
                    "kind": "atomic",
                    "type": "rsi_above",
                    "symbol": "AAPL",
                    "lookback": 14,
                    "threshold": 70,
                },
                "risk": {"cooldown_bars": 0},
                "core_overlay": {"enabled": False, "core_allocation_pct": 0.0},
            }
        },
        max_attempts=1,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    mark_run_succeeded(
        db_session,
        run,
        summary_json={"total_return_pct": 1.0},
        artifact_dir="data/local_artifacts/runs/test-run",
        artifact_manifest_json={"summary_json": "summary.json"},
    )

    response = client.post(
        f"/runs/{run.id}/save-strategy",
        json={"name": "Should fail"},
    )

    assert response.status_code == 400
    assert "not supported yet" in response.json()["detail"]
    assert "ETF-first" in response.json()["detail"]
