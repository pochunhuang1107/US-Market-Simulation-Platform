from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import market_simulator.services.strategy_builder_parsers as builder_parsers
from market_simulator import settings as settings_module
from market_simulator.db.enums import SubscriptionStatus
from market_simulator.db.models.user import Plan, UserPlanSubscription
from market_simulator.settings import Settings
from market_simulator.services.strategy_translation import LlmStructuredTranslationOutput


def _single_etf_config(*, name: str = "qqq-rsi") -> dict:
    return {
        "schema_version": "2.0",
        "name": name,
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


def _rotation_config(*, name: str = "rotation", lookback: int = 63) -> dict:
    return {
        "schema_version": "2.0",
        "name": name,
        "tradable_symbol": "QQQ",
        "benchmark_symbol": "SPY",
        "reference_symbols": ["SPY", "XLK", "TLT"],
        "start_date": "2021-01-01",
        "end_date": "2021-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 0,
        "allocation": None,
        "entry_rule": None,
        "exit_rule": None,
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
        "position_management": None,
        "rotation": {
            "enabled": True,
            "universe": ["QQQ", "SPY", "XLK", "TLT"],
            "ranking": {
                "type": "relative_return",
                "lookback": lookback,
                "descending": True,
            },
            "rebalance": {
                "frequency": "monthly",
                "day": "first_trading_day",
            },
            "selection": {
                "top_n": 1,
            },
            "allocation": {
                "weighting": "equal_weight",
                "max_position_pct": 1.0,
            },
            "risk_filter": None,
            "fallback": {
                "type": "cash",
            },
        },
    }


def _create_plan(
    db_session,
    *,
    code: str,
    allow_rotation_templates: bool,
    allow_custom_rotation: bool,
    allow_rotation_edit: bool,
    allow_advanced_builder: bool,
    allow_parameter_sweeps: bool = False,
) -> Plan:
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=code.replace("_", " ").title(),
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=50,
        max_saved_strategies=50,
        max_tracked_strategies=50,
        builder_prompt_daily_limit=50,
        builder_prompt_max_chars=5000,
        max_backtest_years=10,
        max_comparison_runs=4,
        allow_portfolio_runs=True,
        allow_comparison_runs=True,
        allow_parameter_sweeps=allow_parameter_sweeps,
        allow_ai_builder=True,
        allow_strategy_history=True,
        allow_rotation_templates=allow_rotation_templates,
        allow_custom_rotation=allow_custom_rotation,
        allow_rotation_edit=allow_rotation_edit,
        allow_advanced_builder=allow_advanced_builder,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _attach_plan(db_session, *, user_id: str, plan: Plan) -> None:
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


def _run_payload(config: dict, *, request_payload: dict | None = None) -> dict:
    return {
        "draft_config": config,
        "run_type": "SIMULATION",
        "executor_type": "SIMULATION_EXECUTOR",
        "request_payload": request_payload or {},
        "max_attempts": 1,
    }


def _strategy_payload(config: dict) -> dict:
    return {
        "name": config["name"],
        "description": "Advanced rotation entitlement coverage",
        "strategy_type": "SIMULATION",
        "config": config,
    }


def _assert_rotation_plan_limit(response) -> None:
    assert response.status_code == 403
    body = response.json()
    detail = body["detail"]
    if isinstance(detail, dict):
        text = f"{detail['message']} {detail['guidance']}"
    else:
        text = detail
    assert "Custom rotation strategies require Research access." in text
    assert "You can still run curated Gallery examples within your plan limits." in text
    assert "This is a plan limit, not a strategy validation error." in text


def test_free_cannot_create_custom_rotation_via_builder(
    client,
    db_session,
    create_user,
    current_user_ctx,
    monkeypatch,
):
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE",
        allow_rotation_templates=True,
        allow_custom_rotation=False,
        allow_rotation_edit=False,
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=str(user.id), plan=plan)

    metadata_calls: list[str] = []

    def fail_if_metadata_is_loaded(symbol: str):
        metadata_calls.append(symbol)
        raise AssertionError("FREE custom rotation builder prompt should not load ETF metadata")

    monkeypatch.setattr(builder_parsers, "get_etf_history_range", fail_if_metadata_is_loaded)

    response = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a monthly rotation between QQQ, SPY, XLK, and TLT using 3-month momentum."
        },
    )

    _assert_rotation_plan_limit(response)
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["validation_data"]["validation_type"] == "PLAN_LIMIT"
    assert body["config"] is None
    assert metadata_calls == []


def test_openai_provider_cannot_bypass_custom_rotation_builder_gate(
    client,
    db_session,
    create_user,
    current_user_ctx,
    monkeypatch,
):
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE",
        allow_rotation_templates=True,
        allow_custom_rotation=False,
        allow_rotation_edit=False,
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=str(user.id), plan=plan)
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            strategy_builder_provider="openai",
            openai_api_key="test-key",
        ),
    )

    def mocked_openai_contract(self, request):
        return LlmStructuredTranslationOutput(
            action="create_config",
            full_config=_rotation_config(),
            summary="Translated a rotation Strategy V2 draft.",
        )

    monkeypatch.setattr(
        "market_simulator.services.strategy_translation.OpenAIStrategyTranslationProvider._request_contract",
        mocked_openai_contract,
    )

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a QQQ strategy with a flexible allocation rule."},
    )

    _assert_rotation_plan_limit(response)
    body = response.json()
    assert body["response_type"] == "VALIDATION_ERROR"
    assert body["validation_data"]["validation_type"] == "PLAN_LIMIT"
    assert body["translation_provider"] == "openai"
    assert body["translation_mode"] == "llm"
    assert body["llm_enabled"] is True


def test_free_can_create_normal_single_etf_strategy_via_builder(
    client,
    db_session,
    create_user,
    current_user_ctx,
    monkeypatch,
):
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE",
        allow_rotation_templates=True,
        allow_custom_rotation=False,
        allow_rotation_edit=False,
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=str(user.id), plan=plan)
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)

    response = client.post(
        "/strategy-builder/generate",
        json={"prompt": "Create a mean reversion strategy for QQQ using RSI below 35 and exit above 65."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "CREATE_DRAFT"
    assert body["config"]["tradable_symbol"] == "QQQ"
    assert "rotation" not in body["config"]


def test_free_cannot_run_custom_rotation_config_but_can_run_single_etf_strategy(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE",
        allow_rotation_templates=True,
        allow_custom_rotation=False,
        allow_rotation_edit=False,
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=str(user.id), plan=plan)

    blocked = client.post("/runs", json=_run_payload(_rotation_config(name="custom-rotation")))
    _assert_rotation_plan_limit(blocked)

    allowed = client.post("/runs", json=_run_payload(_single_etf_config(name="single-etf")))
    assert allowed.status_code == 200


def test_free_can_run_curated_gallery_rotation_within_run_limits(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE",
        allow_rotation_templates=True,
        allow_custom_rotation=False,
        allow_rotation_edit=False,
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=str(user.id), plan=plan)

    response = client.post(
        "/runs",
        json=_run_payload(
            _rotation_config(name="gallery-rotation"),
            request_payload={
                "source": "strategy_gallery",
                "template_id": "defensive-cross-asset-252-sma200-rotation",
                "template_title": "Defensive Cross-Asset Rotation",
            },
        ),
    )

    assert response.status_code == 200


def test_beta_tester_can_create_edit_and_run_rotation(
    client,
    db_session,
    create_user,
    current_user_ctx,
    monkeypatch,
):
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="BETA_TESTER",
        allow_rotation_templates=True,
        allow_custom_rotation=True,
        allow_rotation_edit=True,
        allow_advanced_builder=True,
        allow_parameter_sweeps=True,
    )
    _attach_plan(db_session, user_id=str(user.id), plan=plan)
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)

    builder = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a monthly rotation between QQQ, SPY, XLK, and TLT using 3-month momentum."
        },
    )
    assert builder.status_code == 200
    builder_body = builder.json()
    assert builder_body["response_type"] == "CREATE_DRAFT"
    assert builder_body["config"]["rotation"]["enabled"] is True

    created = client.post("/strategies", json=_strategy_payload(_rotation_config(name="Beta Rotation")))
    assert created.status_code == 200

    ids = created.json()
    edited_config = _rotation_config(name="Beta Rotation", lookback=126)
    edited = client.post(
        f"/strategies/{ids['strategy_id']}/versions",
        json={"config": edited_config, "change_note": "longer momentum lookback"},
    )
    assert edited.status_code == 200

    run = client.post("/runs", json=_run_payload(_rotation_config(name="beta-rotation-run")))
    assert run.status_code == 200


def test_dev_admin_override_can_create_edit_and_run_rotation(
    client,
    db_session,
    create_user,
    current_user_ctx,
    monkeypatch,
):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="local",
            auth_mode="dev",
            artifact_storage_backend="LOCAL",
            enable_dev_admin_override=True,
            dev_admin_user_ids_csv=current_user_ctx["id"],
            strategy_builder_provider="deterministic",
            openai_api_key=None,
        ),
    )
    create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    monkeypatch.setattr(builder_parsers, "get_etf_history_range", lambda symbol: None)

    builder = client.post(
        "/strategy-builder/generate",
        json={
            "prompt": "Create a monthly rotation between QQQ, SPY, XLK, and TLT using 3-month momentum."
        },
    )
    assert builder.status_code == 200
    builder_body = builder.json()
    assert builder_body["response_type"] == "CREATE_DRAFT"
    assert builder_body["config"]["rotation"]["enabled"] is True

    created = client.post("/strategies", json=_strategy_payload(_rotation_config(name="Dev Rotation")))
    assert created.status_code == 200

    ids = created.json()
    edited = client.post(
        f"/strategies/{ids['strategy_id']}/versions",
        json={
            "config": _rotation_config(name="Dev Rotation", lookback=126),
            "change_note": "dev override rotation edit",
        },
    )
    assert edited.status_code == 200

    run = client.post("/runs", json=_run_payload(_rotation_config(name="dev-rotation-run")))
    assert run.status_code == 200


def test_entitlement_response_includes_advanced_rotation_fields(
    client,
    db_session,
    create_user,
    current_user_ctx,
):
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE",
        allow_rotation_templates=True,
        allow_custom_rotation=False,
        allow_rotation_edit=False,
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=str(user.id), plan=plan)

    response = client.get("/me/entitlements")

    assert response.status_code == 200
    features = response.json()["features"]
    assert features["allow_rotation_templates"] is True
    assert features["allow_custom_rotation"] is False
    assert features["allow_rotation_edit"] is False
    assert features["allow_advanced_builder"] is False
    assert features["allow_parameter_sweeps"] is False
