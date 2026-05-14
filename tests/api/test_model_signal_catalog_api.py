from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy.orm import Session

from market_simulator import settings as settings_module
from market_simulator.db.enums import SubscriptionStatus
from market_simulator.db.models.user import Plan, UserPlanSubscription
from market_simulator.services import model_signal_catalog as catalog_module
from market_simulator.settings import Settings


MODEL_VERSION = "linear_smooth10_margin002_v1"


def _create_plan(
    db_session: Session,
    *,
    code: str,
    allow_advanced_builder: bool,
) -> Plan:
    plan = Plan(
        id=uuid.uuid4(),
        code=code,
        name=code.replace("_", " ").title(),
        monthly_price_usd=Decimal("0.00"),
        daily_free_runs=100,
        max_saved_strategies=100,
        max_tracked_strategies=100,
        builder_prompt_daily_limit=100,
        builder_prompt_max_chars=5000,
        max_backtest_years=25,
        max_comparison_runs=4,
        allow_portfolio_runs=True,
        allow_comparison_runs=True,
        allow_parameter_sweeps=True,
        allow_ai_builder=True,
        allow_strategy_history=True,
        allow_rotation_templates=True,
        allow_custom_rotation=allow_advanced_builder,
        allow_rotation_edit=allow_advanced_builder,
        allow_advanced_builder=allow_advanced_builder,
        is_active=True,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def _attach_plan(db_session: Session, *, user_id: uuid.UUID, plan: Plan) -> None:
    subscription = UserPlanSubscription(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=datetime.now(timezone.utc) - timedelta(days=1),
        ends_at=None,
        auto_renew=False,
        provider=None,
        provider_subscription_id=None,
    )
    db_session.add(subscription)
    db_session.commit()


def _write_current_preview_artifact(base_path) -> None:
    version_dir = base_path / f"model_version={MODEL_VERSION}"
    version_dir.mkdir()
    pd.DataFrame(
        {
            "date": ["2026-05-01", "2026-05-08", "2026-05-08", "2026-05-08"],
            "symbol": ["QQQ", "SLV", "VUG", "SPY"],
            "model_version": [MODEL_VERSION] * 4,
            "score": [99.0, 0.01427497862217832, -0.0485, -0.2],
            "rank": [1, 2, 1, 3],
            "confidence": [0.9, 0.7, 0.88, 0.95],
            "signal_bucket": ["top", "unselected", "top", "unselected"],
        }
    ).to_csv(version_dir / "signals.csv", index=False)
    (version_dir / "model_signal_manifest.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "latest_signal_date": "2026-05-08",
                "status": "ready",
                "warnings": ["synthetic fixture warning"],
                "artifact_path": "/Users/local/export/signals.parquet",
            }
        ),
        encoding="utf-8",
    )


def test_catalog_lists_linear_model_for_entitled_user(
    client,
    create_user,
    current_user_ctx,
) -> None:
    user = create_user(user_id=current_user_ctx["id"])

    response = client.get("/model-signals/catalog")

    assert response.status_code == 200
    body = response.json()
    assert [model["model_version"] for model in body["models"]] == [MODEL_VERSION]
    assert body["models"][0]["display_name"] == "Linear Smooth 10 Margin 0.002"
    assert body["models"][0]["recommended_defaults"]["top_n"] == 1
    assert str(user.id) == current_user_ctx["id"]


def test_catalog_detail_returns_metadata_risk_notes_and_defaults(
    client,
    create_user,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])

    response = client.get(f"/model-signals/catalog/{MODEL_VERSION}")

    assert response.status_code == 200
    model = response.json()
    assert model["model_version"] == MODEL_VERSION
    assert model["research_status"] == "paper_tracking"
    assert model["ranking_field"] == "score"
    assert model["default_signal_bucket_filter"] == ["top"]
    assert model["default_fallback"] == {"type": "cash", "symbol": None}
    assert model["label_horizon_days"] == 20
    assert model["feature_set_version"] == "default_features_v1"
    assert "MODEL_SIGNAL_DATA_PATH" == model["artifact_path_setting"]
    assert "linear_smooth10_margin002_v1" in model["artifact_path_hint"]
    assert any("not investment advice" in note for note in model["risk_notes"])
    assert model["recommended_defaults"]["benchmark"] == "SPY"


def test_disabled_model_is_not_listed_by_default(
    client,
    create_user,
    current_user_ctx,
    monkeypatch,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    disabled = replace(
        catalog_module.MODEL_SIGNAL_REGISTRY[MODEL_VERSION],
        model_version="disabled_internal_model_v0",
        display_name="Disabled Internal Model",
        enabled=False,
    )
    monkeypatch.setattr(
        catalog_module,
        "MODEL_SIGNAL_REGISTRY",
        {
            **catalog_module.MODEL_SIGNAL_REGISTRY,
            disabled.model_version: disabled,
        },
    )

    response = client.get("/model-signals/catalog")

    assert response.status_code == 200
    model_versions = [model["model_version"] for model in response.json()["models"]]
    assert MODEL_VERSION in model_versions
    assert disabled.model_version not in model_versions


def test_non_entitled_user_is_blocked(
    client,
    db_session,
    create_user,
    current_user_ctx,
) -> None:
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE_MODEL_SIGNAL_TEST",
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=user.id, plan=plan)

    response = client.get("/model-signals/catalog")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PLAN_LIMIT_MODEL_SIGNALS"


def test_catalog_response_does_not_leak_local_absolute_paths(
    client,
    create_user,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])

    response = client.get(f"/model-signals/catalog/{MODEL_VERSION}")

    assert response.status_code == 200
    serialized = json.dumps(response.json())
    assert "/Users/" not in serialized
    assert "/tmp/" not in serialized
    assert "C:\\" not in serialized
    assert "MODEL_SIGNAL_DATA_PATH" in serialized


def test_current_preview_returns_latest_selected_signal_for_entitled_user(
    client,
    create_user,
    current_user_ctx,
    tmp_path,
    monkeypatch,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    _write_current_preview_artifact(tmp_path)
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            model_signal_data_path=str(tmp_path),
            artifact_storage_backend="LOCAL",
        ),
    )

    response = client.get(f"/model-signals/catalog/{MODEL_VERSION}/current")

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == MODEL_VERSION
    assert body["latest_signal_date"] == "2026-05-08"
    assert body["selected_symbols"] == ["VUG"]
    assert body["selected_rows"][0]["score"] == -0.0485
    assert body["selected_rows"][0]["signal_bucket"] == "top"
    assert body["manifest_status"] == "ready"
    assert body["manifest_warnings"] == ["synthetic fixture warning"]
    serialized = json.dumps(body)
    assert str(tmp_path) not in serialized
    assert "/Users/local/export" not in serialized


def test_current_preview_blocks_non_entitled_user(
    client,
    db_session,
    create_user,
    current_user_ctx,
) -> None:
    user = create_user(user_id=current_user_ctx["id"], with_default_plan=False)
    plan = _create_plan(
        db_session,
        code="FREE_MODEL_SIGNAL_CURRENT_TEST",
        allow_advanced_builder=False,
    )
    _attach_plan(db_session, user_id=user.id, plan=plan)

    response = client.get(f"/model-signals/catalog/{MODEL_VERSION}/current")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PLAN_LIMIT_MODEL_SIGNALS"


def test_current_preview_missing_artifact_returns_controlled_error_without_path(
    client,
    create_user,
    current_user_ctx,
    tmp_path,
    monkeypatch,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    missing_path = tmp_path / "missing"
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            model_signal_data_path=str(missing_path),
            artifact_storage_backend="LOCAL",
        ),
    )

    response = client.get(f"/model-signals/catalog/{MODEL_VERSION}/current")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "MODEL_SIGNAL_ARTIFACT_NOT_FOUND"
    assert str(missing_path) not in json.dumps(body)
