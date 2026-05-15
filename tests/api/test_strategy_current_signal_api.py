from __future__ import annotations

import json

import pandas as pd

from market_simulator import settings as settings_module
from market_simulator.services.model_signal_catalog import build_model_signal_strategy_config
from market_simulator.settings import Settings


MODEL_VERSION = "linear_smooth10_margin002_v1"


def _model_signal_config() -> dict:
    return build_model_signal_strategy_config(
        model_version=MODEL_VERSION,
        start_date="2026-01-01",
        end_date="2026-12-31",
        universe=["QQQ", "VUG", "SLV"],
        top_n=1,
        signal_bucket_filter=["top"],
        fallback={"type": "cash"},
        name="Saved Model Signal",
    )


def _write_artifact(base_path, *, selected_symbol: str = "SLV") -> None:
    version_dir = base_path / f"model_version={MODEL_VERSION}"
    version_dir.mkdir(parents=True)
    scores = {
        "QQQ": 0.95,
        "VUG": 0.4,
        "SLV": 0.7,
        selected_symbol: 0.99,
    }
    pd.DataFrame(
        {
            "date": ["2026-05-01", "2026-05-08", "2026-05-08", "2026-05-08"],
            "symbol": ["QQQ", "QQQ", "VUG", "SLV"],
            "model_version": [MODEL_VERSION] * 4,
            "score": [0.2, scores["QQQ"], scores["VUG"], scores["SLV"]],
            "rank": [
                1,
                1 if selected_symbol == "QQQ" else 2,
                1 if selected_symbol == "VUG" else 3,
                1 if selected_symbol == "SLV" else 2,
            ],
            "predicted_return": [0.01, 0.05, 0.01, 0.04],
            "confidence": [0.9, 0.6, 0.95, 0.7],
            "signal_bucket": ["top", "top", "top", "top"],
        }
    ).to_csv(version_dir / "signals.csv", index=False)
    (version_dir / "model_signal_manifest.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "latest_signal_date": "2026-05-08",
                "status": "ready",
                "warnings": ["synthetic current signal fixture"],
                "artifact_path": "/Users/private/model/signals.parquet",
            }
        ),
        encoding="utf-8",
    )


def test_owner_can_get_current_signal_for_saved_model_strategy(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    tmp_path,
    monkeypatch,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(),
    )
    historical_path = tmp_path / "historical"
    current_path = tmp_path / "current"
    _write_artifact(historical_path, selected_symbol="SLV")
    _write_artifact(current_path, selected_symbol="VUG")
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

    response = client.get(f"/strategies/{strategy.id}/current-signal")

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == str(strategy.id)
    assert body["strategy_version_id"] == str(version.id)
    assert body["model_version"] == MODEL_VERSION
    assert body["as_of_date"] == "2026-05-08"
    assert body["latest_signal_date"] == "2026-05-08"
    assert body["selected_symbols"] == ["VUG"]
    assert body["target_weights"] == {"VUG": 1.0}
    assert body["selected_rows"][0]["score"] == 0.99
    assert body["selected_rows"][0]["signal_bucket"] == "top"
    assert body["fallback_used"] is False
    assert body["manifest_status"] == "ready"
    assert body["manifest_warnings"] == ["synthetic current signal fixture"]
    assert body["source"]["label"] == "current artifact"
    serialized = json.dumps(body)
    assert str(historical_path) not in serialized
    assert str(current_path) not in serialized
    assert "/Users/private/model" not in serialized


def test_current_signal_accepts_current_user_object_from_auth_dependency(
    real_auth_client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    tmp_path,
    monkeypatch,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(),
    )
    _write_artifact(tmp_path, selected_symbol="VUG")
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            model_signal_data_path=str(tmp_path),
            model_signal_current_data_path="",
            artifact_storage_backend="LOCAL",
        ),
    )

    response = real_auth_client.get(
        f"/strategies/{strategy.id}/current-signal?strategy_version_id={version.id}",
        headers={"X-User-Id": current_user_ctx["id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == str(strategy.id)
    assert body["strategy_version_id"] == str(version.id)
    assert body["selected_symbols"] == ["VUG"]


def test_current_signal_blocks_non_owner(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    tmp_path,
    monkeypatch,
) -> None:
    owner_id = "00000000-0000-0000-0000-000000000020"
    create_user(user_id=current_user_ctx["id"])
    create_user(user_id=owner_id)
    strategy, _ = create_strategy_bundle(
        user_id=owner_id,
        config_json=_model_signal_config(),
    )
    _write_artifact(tmp_path)
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            model_signal_data_path=str(tmp_path),
            model_signal_current_data_path="",
            artifact_storage_backend="LOCAL",
        ),
    )

    response = client.get(f"/strategies/{strategy.id}/current-signal")

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy not found"


def test_current_signal_non_model_strategy_returns_controlled_error(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, _ = create_strategy_bundle(user_id=current_user_ctx["id"])

    response = client.get(f"/strategies/{strategy.id}/current-signal")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "STRATEGY_NOT_MODEL_SIGNAL"


def test_current_signal_as_of_date_uses_latest_signal_on_or_before_date(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    tmp_path,
    monkeypatch,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(),
    )
    _write_artifact(tmp_path)
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            model_signal_data_path=str(tmp_path),
            model_signal_current_data_path="",
            artifact_storage_backend="LOCAL",
        ),
    )

    response = client.get(f"/strategies/{strategy.id}/current-signal?as_of_date=2026-05-02")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of_date"] == "2026-05-02"
    assert body["latest_signal_date"] == "2026-05-01"
    assert body["selected_symbols"] == ["QQQ"]


def test_current_signal_missing_artifact_returns_controlled_error_without_path(
    client,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
    tmp_path,
    monkeypatch,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(),
    )
    missing_path = tmp_path / "missing"
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            env="test",
            auth_mode="dev",
            model_signal_data_path=str(missing_path),
            model_signal_current_data_path="",
            artifact_storage_backend="LOCAL",
        ),
    )

    response = client.get(f"/strategies/{strategy.id}/current-signal")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "MODEL_SIGNAL_ARTIFACT_NOT_FOUND"
    assert str(missing_path) not in json.dumps(body)
