from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

import market_simulator.services.entitlements as entitlements_module
import market_simulator.settings as settings_module
from market_simulator.db.enums import RunStatus, StrategyStatus, SubscriptionStatus
from market_simulator.db.models.builder_prompt_event import BuilderPromptEvent
from market_simulator.db.models.run import Run
from market_simulator.db.models.strategy import Strategy
from market_simulator.db.models.user import Plan, UserPlanSubscription
from market_simulator.repositories.runs import create_run, mark_run_succeeded
from market_simulator.services.entitlements import get_user_entitlements


def _strategy_v2_config(
    *,
    name: str = "qqq-rsi",
    start_date: str = "2021-01-01",
    end_date: str = "2021-12-31",
) -> dict:
    return {
        "schema_version": "2.0",
        "name": name,
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "QQQ",
        "reference_symbols": [],
        "start_date": start_date,
        "end_date": end_date,
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


def _create_plan(
    db_session,
    *,
    code: str,
    daily_free_runs: int = 10,
    max_saved_strategies: int = 10,
    builder_prompt_daily_limit: int = 10,
    builder_prompt_max_chars: int = 1000,
    max_backtest_years: int = 10,
    max_comparison_runs: int = 4,
    allow_ai_builder: bool = True,
    allow_comparison_runs: bool = True,
    allow_parameter_sweeps: bool = True,
    allow_strategy_history: bool = True,
) -> Plan:
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=code.title(),
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=daily_free_runs,
        max_saved_strategies=max_saved_strategies,
        max_tracked_strategies=10,
        builder_prompt_daily_limit=builder_prompt_daily_limit,
        builder_prompt_max_chars=builder_prompt_max_chars,
        max_backtest_years=max_backtest_years,
        max_comparison_runs=max_comparison_runs,
        allow_portfolio_runs=True,
        allow_comparison_runs=allow_comparison_runs,
        allow_parameter_sweeps=allow_parameter_sweeps,
        allow_ai_builder=allow_ai_builder,
        allow_strategy_history=allow_strategy_history,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _attach_plan(db_session, *, user_id: str, plan: Plan) -> UserPlanSubscription:
    subscription = UserPlanSubscription(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=datetime.now(timezone.utc) - timedelta(days=1),
        ends_at=None,
        auto_renew=False,
    )
    db_session.add(subscription)
    db_session.commit()
    db_session.refresh(subscription)
    return subscription


def _run_payload(*, note: str, config: dict | None = None) -> dict:
    return {
        "draft_config": config or _strategy_v2_config(name=note),
        "run_type": "SIMULATION",
        "executor_type": "SIMULATION_EXECUTOR",
        "request_payload": {"note": note},
        "max_attempts": 1,
    }


def _strategy_payload(*, name: str, config: dict | None = None) -> dict:
    return {
        "name": name,
        "description": "Regression coverage strategy",
        "strategy_type": "SIMULATION",
        "config": config or _strategy_v2_config(name=name),
    }


def _succeeded_run(db_session, *, user_id: str, note: str) -> Run:
    run = create_run(
        db_session,
        user_id,
        None,
        None,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {"note": note},
        max_attempts=1,
    )
    run.status = RunStatus.RUNNING
    db_session.commit()
    db_session.refresh(run)

    return mark_run_succeeded(
        db_session,
        run,
        summary_json={
            "total_return_pct": 10.0,
            "benchmark_return_pct": 8.0,
            "alpha_vs_benchmark_pct": 2.0,
        },
        artifact_dir=f"data/local_artifacts/runs/{run.id}",
        artifact_manifest_json={"summary": f"summary-{run.id}.json"},
    )


def test_daily_run_limit_allows_within_limit_denies_over_limit_and_is_per_current_user(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user_a = create_user(user_id=str(uuid.uuid4()), email="run-limit-a@example.com", with_default_plan=False)
    user_b = create_user(user_id=str(uuid.uuid4()), email="run-limit-b@example.com", with_default_plan=False)
    plan = _create_plan(db_session, code="RUN_LIMIT", daily_free_runs=2)
    _attach_plan(db_session, user_id=str(user_a.id), plan=plan)
    _attach_plan(db_session, user_id=str(user_b.id), plan=plan)

    current_user_ctx["id"] = str(user_a.id)
    assert client.post("/runs", json=_run_payload(note="a-1")).status_code == 200
    assert client.post("/runs", json=_run_payload(note="a-2")).status_code == 200

    over_limit = client.post("/runs", json=_run_payload(note="a-3"))
    assert over_limit.status_code == 403
    assert "Daily run limit reached" in over_limit.json()["detail"]

    current_user_ctx["id"] = str(user_b.id)
    response = client.post("/runs", json=_run_payload(note="b-1"))
    assert response.status_code == 200
    assert response.json()["user_id"] == str(user_b.id)


def test_saved_strategy_limit_counts_active_strategies_for_current_user_and_ignores_archived(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user_a = create_user(user_id=str(uuid.uuid4()), email="strategy-limit-a@example.com", with_default_plan=False)
    user_b = create_user(user_id=str(uuid.uuid4()), email="strategy-limit-b@example.com", with_default_plan=False)
    plan = _create_plan(db_session, code="STRATEGY_LIMIT", max_saved_strategies=1)
    _attach_plan(db_session, user_id=str(user_a.id), plan=plan)
    _attach_plan(db_session, user_id=str(user_b.id), plan=plan)

    current_user_ctx["id"] = str(user_a.id)
    created = client.post("/strategies", json=_strategy_payload(name="First active"))
    assert created.status_code == 200

    denied = client.post("/strategies", json=_strategy_payload(name="Second active"))
    assert denied.status_code == 403
    assert "Saved strategy limit reached" in denied.json()["detail"]

    current_user_ctx["id"] = str(user_b.id)
    other_user_create = client.post("/strategies", json=_strategy_payload(name="Other user active"))
    assert other_user_create.status_code == 200

    current_user_ctx["id"] = str(user_a.id)
    archived = client.post(f"/strategies/{created.json()['strategy_id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == StrategyStatus.ARCHIVED

    replacement = client.post("/strategies", json=_strategy_payload(name="Replacement active"))
    assert replacement.status_code == 200


def test_builder_access_prompt_limits_and_rejected_prompt_events_are_backend_enforced(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    blocked_user = create_user(user_id=str(uuid.uuid4()), email="builder-blocked@example.com", with_default_plan=False)
    limited_user = create_user(user_id=str(uuid.uuid4()), email="builder-limited@example.com", with_default_plan=False)
    other_user = create_user(user_id=str(uuid.uuid4()), email="builder-other@example.com", with_default_plan=False)
    blocked_plan = _create_plan(db_session, code="NO_BUILDER", allow_ai_builder=False)
    limited_plan = _create_plan(
        db_session,
        code="PROMPT_LIMIT",
        builder_prompt_daily_limit=1,
        builder_prompt_max_chars=80,
    )
    _attach_plan(db_session, user_id=str(blocked_user.id), plan=blocked_plan)
    _attach_plan(db_session, user_id=str(limited_user.id), plan=limited_plan)
    _attach_plan(db_session, user_id=str(other_user.id), plan=limited_plan)

    current_user_ctx["id"] = str(blocked_user.id)
    blocked = client.post("/strategy-builder/generate", json={"prompt": "Create a QQQ strategy"})
    assert blocked.status_code == 403
    assert "strategy builder access" in blocked.json()["detail"]

    current_user_ctx["id"] = str(limited_user.id)
    accepted = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a QQQ strategy from 2021-01-01 to 2021-12-31"},
    )
    assert accepted.status_code == 200

    daily_denied = client.post("/strategy-builder/generate", json={"prompt": "Adjust RSI entry to 25"})
    assert daily_denied.status_code == 403
    assert "Daily builder prompt limit reached" in daily_denied.json()["detail"]

    current_user_ctx["id"] = str(other_user.id)
    too_long = client.post("/strategy-builder/generate", json={"prompt": "x" * 81})
    assert too_long.status_code == 400
    assert "Prompt exceeds your plan limit" in too_long.json()["detail"]

    events = db_session.query(BuilderPromptEvent).order_by(BuilderPromptEvent.created_at).all()
    by_user = {(str(event.user_id), event.status, event.rejection_reason) for event in events}
    assert (str(blocked_user.id), "REJECTED", "BUILDER_NOT_ALLOWED") in by_user
    assert (str(limited_user.id), "ACCEPTED", None) in by_user
    assert (str(limited_user.id), "REJECTED", "DAILY_PROMPT_LIMIT_REACHED") in by_user
    assert (str(other_user.id), "REJECTED", "PROMPT_TOO_LONG") in by_user


def test_compare_limit_and_compare_feature_flag_are_enforced_per_current_user(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user_a = create_user(user_id=str(uuid.uuid4()), email="compare-limit-a@example.com", with_default_plan=False)
    user_b = create_user(user_id=str(uuid.uuid4()), email="compare-limit-b@example.com", with_default_plan=False)
    no_compare_user = create_user(user_id=str(uuid.uuid4()), email="compare-disabled@example.com", with_default_plan=False)
    plan_two = _create_plan(db_session, code="COMPARE_TWO", max_comparison_runs=2)
    plan_three = _create_plan(db_session, code="COMPARE_THREE", max_comparison_runs=3)
    plan_disabled = _create_plan(
        db_session,
        code="COMPARE_DISABLED",
        max_comparison_runs=3,
        allow_comparison_runs=False,
    )
    _attach_plan(db_session, user_id=str(user_a.id), plan=plan_two)
    _attach_plan(db_session, user_id=str(user_b.id), plan=plan_three)
    _attach_plan(db_session, user_id=str(no_compare_user.id), plan=plan_disabled)

    a_runs = [_succeeded_run(db_session, user_id=str(user_a.id), note=f"a-{idx}") for idx in range(3)]
    b_runs = [_succeeded_run(db_session, user_id=str(user_b.id), note=f"b-{idx}") for idx in range(3)]
    disabled_runs = [
        _succeeded_run(db_session, user_id=str(no_compare_user.id), note=f"disabled-{idx}")
        for idx in range(2)
    ]

    current_user_ctx["id"] = str(user_a.id)
    a_ids = ",".join(str(run.id) for run in a_runs)
    compare_denied = client.get(f"/runs/compare?run_ids={a_ids}")
    chart_denied = client.get(f"/runs/compare/chart?run_ids={a_ids}")
    assert compare_denied.status_code == 403
    assert "Select up to 2 runs" in compare_denied.json()["detail"]
    assert chart_denied.status_code == 403
    assert "Select up to 2 runs" in chart_denied.json()["detail"]

    current_user_ctx["id"] = str(user_b.id)
    b_ids = ",".join(str(run.id) for run in b_runs)
    allowed = client.get(f"/runs/compare?run_ids={b_ids}")
    assert allowed.status_code == 200
    assert len(allowed.json()["runs"]) == 3

    current_user_ctx["id"] = str(no_compare_user.id)
    disabled_ids = ",".join(str(run.id) for run in disabled_runs)
    disabled = client.get(f"/runs/compare?run_ids={disabled_ids}")
    assert disabled.status_code == 403
    assert "comparison runs" in disabled.json()["detail"]


def test_parameter_sweep_access_and_variant_cap_are_enforced_server_side(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    disabled_user = create_user(user_id=str(uuid.uuid4()), email="sweep-disabled@example.com", with_default_plan=False)
    capped_user = create_user(user_id=str(uuid.uuid4()), email="sweep-capped@example.com", with_default_plan=False)
    disabled_plan = _create_plan(db_session, code="NO_SWEEPS", allow_parameter_sweeps=False)
    capped_plan = _create_plan(db_session, code="SWEEP_CAP", allow_parameter_sweeps=True)
    _attach_plan(db_session, user_id=str(disabled_user.id), plan=disabled_plan)
    _attach_plan(db_session, user_id=str(capped_user.id), plan=capped_plan)

    payload = {
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
        "max_attempts": 1,
    }

    current_user_ctx["id"] = str(disabled_user.id)
    disabled = client.post("/runs", json=payload)
    assert disabled.status_code == 403
    assert "parameter sweeps" in disabled.json()["detail"]

    current_user_ctx["id"] = str(capped_user.id)
    capped = client.post("/runs", json=payload)
    assert capped.status_code == 400
    assert capped.json()["detail"] == "Parameter sweep is limited to 3 variants for your plan."


def test_backtest_year_limit_is_enforced_for_draft_runs_strategy_create_and_versions(
    client,
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
):
    user = create_user(user_id=str(uuid.uuid4()), email="backtest-limit@example.com", with_default_plan=False)
    plan = _create_plan(db_session, code="ONE_YEAR", max_backtest_years=1)
    _attach_plan(db_session, user_id=str(user.id), plan=plan)
    current_user_ctx["id"] = str(user.id)

    long_config = _strategy_v2_config(name="long-window", start_date="2021-01-01", end_date="2024-01-01")

    draft_run = client.post("/runs", json=_run_payload(note="long-draft", config=long_config))
    assert draft_run.status_code == 400
    assert "plan limit of 1 years" in draft_run.json()["detail"]

    strategy_create = client.post("/strategies", json=_strategy_payload(name="Long strategy", config=long_config))
    assert strategy_create.status_code == 400
    assert "plan limit of 1 years" in strategy_create.json()["detail"]

    strategy, _ = create_strategy_bundle(
        user_id=str(user.id),
        strategy_name="Short strategy",
        config_json=_strategy_v2_config(name="Short strategy"),
    )
    version_create = client.post(
        f"/strategies/{strategy.id}/versions",
        json={"config": long_config, "change_note": "too long"},
    )
    assert version_create.status_code == 400
    assert "plan limit of 1 years" in version_create.json()["detail"]


def test_dev_admin_override_only_applies_to_configured_local_admins(
    db_session,
    monkeypatch,
):
    admin_id = str(uuid.uuid4())
    normal_id = str(uuid.uuid4())
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    settings = settings_module.Settings(
        env="local",
        enable_dev_admin_override=True,
        dev_admin_user_ids_csv=admin_id,
        dev_admin_daily_free_runs=123,
    )
    monkeypatch.setattr(entitlements_module, "get_settings", lambda: settings)

    admin_entitlements = get_user_entitlements(db_session, admin_id)
    assert admin_entitlements.plan_code == "DEV_ADMIN"
    assert admin_entitlements.daily_free_runs == 123
    assert admin_entitlements.allow_ai_builder is True
    assert admin_entitlements.allow_parameter_sweeps is True

    with pytest.raises(HTTPException) as exc_info:
        get_user_entitlements(db_session, normal_id)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "No active subscription plan found"
