from __future__ import annotations

import pandas as pd
import pytest

from market_simulator import settings as settings_module
from market_simulator.auth.current_user import CurrentUser
from market_simulator.services.model_signal_catalog import build_model_signal_strategy_config
from market_simulator.services.saved_strategy_current_signal import (
    SavedStrategyCurrentSignalNotFoundError,
    SavedStrategyCurrentSignalNotModelSignalError,
    SavedStrategyCurrentSignalRequest,
    evaluate_current_signal_for_saved_strategy,
)
from market_simulator.settings import Settings


MODEL_VERSION = "linear_smooth10_margin002_v1"


def _model_signal_config(**overrides) -> dict:
    config = build_model_signal_strategy_config(
        model_version=MODEL_VERSION,
        start_date="2026-01-01",
        end_date="2026-12-31",
        universe=["QQQ", "VUG", "SLV"],
        top_n=overrides.pop("top_n", 1),
        signal_bucket_filter=overrides.pop("signal_bucket_filter", ["top"]),
        min_confidence=overrides.pop("min_confidence", None),
        fallback=overrides.pop("fallback", {"type": "cash"}),
        name="Saved Model Signal",
    )
    config["model_signal"].update(overrides)
    return config


def _signal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                "2026-05-01",
                "2026-05-01",
                "2026-05-08",
                "2026-05-08",
                "2026-05-08",
                "2026-05-15",
                "2026-05-15",
            ],
            "symbol": ["QQQ", "VUG", "QQQ", "VUG", "SLV", "QQQ", "VUG"],
            "model_version": [MODEL_VERSION] * 7,
            "score": [0.2, 0.5, 0.95, 0.4, 0.7, 0.8, 0.9],
            "rank": [2, 1, 1, 3, 2, 2, 1],
            "predicted_return": [0.01, 0.02, 0.05, 0.01, 0.04, 0.03, 0.06],
            "confidence": [0.9, 0.8, 0.6, 0.95, 0.7, 0.4, 0.99],
            "signal_bucket": [
                "top",
                "top",
                "unselected",
                "top",
                "top",
                "top",
                "top",
            ],
        }
    )


def _write_signal_artifact(base_path, *, selected_symbol: str) -> None:
    version_dir = base_path / f"model_version={MODEL_VERSION}"
    version_dir.mkdir(parents=True)
    symbols = ["QQQ", "VUG", "SLV"]
    scores = {
        "QQQ": 0.2,
        "VUG": 0.4,
        "SLV": 0.6,
        selected_symbol: 0.95,
    }
    pd.DataFrame(
        {
            "date": ["2026-05-15"] * len(symbols),
            "symbol": symbols,
            "model_version": [MODEL_VERSION] * len(symbols),
            "score": [scores[symbol] for symbol in symbols],
            "rank": [1 if symbol == selected_symbol else 2 for symbol in symbols],
            "signal_bucket": ["top"] * len(symbols),
        }
    ).to_csv(version_dir / "signals.csv", index=False)


def test_owner_can_evaluate_current_signal_for_saved_model_strategy(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(top_n=2),
    )

    result = evaluate_current_signal_for_saved_strategy(
        db_session,
        SavedStrategyCurrentSignalRequest(
            strategy_id=str(strategy.id),
            current_user=current_user_ctx,
            frame=_signal_frame(),
        ),
    )

    assert result["strategy_id"] == str(strategy.id)
    assert result["strategy_version_id"] == str(version.id)
    assert result["latest_signal_date"] == "2026-05-15"
    assert result["selected_symbols"] == ["VUG", "QQQ"]
    assert result["target_weights"] == {"VUG": 0.5, "QQQ": 0.5}
    assert result["selected_rows"][0]["score"] == 0.9
    assert result["selected_rows"][0]["rank"] == 1
    assert result["fallback_used"] is False


def test_current_user_object_can_evaluate_current_signal_for_saved_model_strategy(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, version = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(),
    )
    current_user = CurrentUser(
        id=current_user_ctx["id"],
        email="saved-signal-owner@example.com",
        display_name="Saved Signal Owner",
        status="ACTIVE",
    )

    result = evaluate_current_signal_for_saved_strategy(
        db_session,
        SavedStrategyCurrentSignalRequest(
            strategy_id=str(strategy.id),
            strategy_version_id=str(version.id),
            current_user=current_user,
            frame=_signal_frame(),
        ),
    )

    assert result["strategy_id"] == str(strategy.id)
    assert result["strategy_version_id"] == str(version.id)
    assert result["selected_symbols"] == ["VUG"]


def test_saved_strategy_current_signal_uses_current_data_path_when_configured(
    db_session,
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
    historical_path = tmp_path / "historical"
    current_path = tmp_path / "current"
    _write_signal_artifact(historical_path, selected_symbol="SLV")
    _write_signal_artifact(current_path, selected_symbol="VUG")
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            model_signal_data_path=str(historical_path),
            model_signal_current_data_path=str(current_path),
        ),
    )

    result = evaluate_current_signal_for_saved_strategy(
        db_session,
        SavedStrategyCurrentSignalRequest(
            strategy_id=str(strategy.id),
            current_user=current_user_ctx,
        ),
    )

    assert result["selected_symbols"] == ["VUG"]
    assert result["source"]["label"] == "current artifact"


def test_non_owner_is_blocked(
    db_session,
    create_user,
    create_strategy_bundle,
) -> None:
    owner_id = "00000000-0000-0000-0000-000000000010"
    other_id = "00000000-0000-0000-0000-000000000011"
    create_user(user_id=owner_id)
    create_user(user_id=other_id)
    strategy, _ = create_strategy_bundle(
        user_id=owner_id,
        config_json=_model_signal_config(),
    )

    with pytest.raises(SavedStrategyCurrentSignalNotFoundError):
        evaluate_current_signal_for_saved_strategy(
            db_session,
            SavedStrategyCurrentSignalRequest(
                strategy_id=str(strategy.id),
                current_user={"id": other_id},
                frame=_signal_frame(),
            ),
        )


def test_non_model_signal_strategy_returns_controlled_error(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, _ = create_strategy_bundle(user_id=current_user_ctx["id"])

    with pytest.raises(SavedStrategyCurrentSignalNotModelSignalError):
        evaluate_current_signal_for_saved_strategy(
            db_session,
            SavedStrategyCurrentSignalRequest(
                strategy_id=str(strategy.id),
                current_user=current_user_ctx,
                frame=_signal_frame(),
            ),
        )


def test_as_of_date_uses_latest_signal_on_or_before_date(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(),
    )

    result = evaluate_current_signal_for_saved_strategy(
        db_session,
        SavedStrategyCurrentSignalRequest(
            strategy_id=str(strategy.id),
            current_user=current_user_ctx,
            as_of_date="2026-05-10",
            frame=_signal_frame(),
        ),
    )

    assert result["as_of_date"] == "2026-05-10"
    assert result["latest_signal_date"] == "2026-05-08"
    assert result["selected_symbols"] == ["SLV"]
    assert result["selected_rows"][0]["signal_bucket"] == "top"


def test_signal_bucket_filter_applies_before_ranking(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(signal_bucket_filter=["top"]),
    )

    result = evaluate_current_signal_for_saved_strategy(
        db_session,
        SavedStrategyCurrentSignalRequest(
            strategy_id=str(strategy.id),
            current_user=current_user_ctx,
            as_of_date="2026-05-08",
            frame=_signal_frame(),
        ),
    )

    assert result["selected_symbols"] == ["SLV"]
    assert result["selected_rows"][0]["score"] == 0.7
    assert result["selected_rows"][0]["signal_bucket"] == "top"


def test_fallback_used_when_no_eligible_signals(
    db_session,
    create_user,
    create_strategy_bundle,
    current_user_ctx,
) -> None:
    create_user(user_id=current_user_ctx["id"])
    strategy, _ = create_strategy_bundle(
        user_id=current_user_ctx["id"],
        config_json=_model_signal_config(
            min_confidence=1.0,
            fallback={"type": "asset", "symbol": "GLD"},
        ),
    )

    result = evaluate_current_signal_for_saved_strategy(
        db_session,
        SavedStrategyCurrentSignalRequest(
            strategy_id=str(strategy.id),
            current_user=current_user_ctx,
            frame=_signal_frame(),
        ),
    )

    assert result["fallback_used"] is True
    assert result["fallback_type"] == "asset"
    assert result["fallback_symbol"] == "GLD"
    assert result["selected_symbols"] == ["GLD"]
    assert result["target_weights"] == {"GLD": 1.0}
    assert result["selected_rows"] == []
