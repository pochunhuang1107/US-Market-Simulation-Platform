from __future__ import annotations

import json

import pandas as pd
import pytest

from market_simulator.services.model_signal_preview import (
    ModelSignalPreviewInvalidError,
    ModelSignalPreviewNotFoundError,
    preview_current_model_signal,
)


MODEL_VERSION = "linear_smooth10_margin002_v1"


def _preview_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                "2026-05-01",
                "2026-05-01",
                "2026-05-08",
                "2026-05-08",
                "2026-05-08",
            ],
            "symbol": ["QQQ", "VUG", "QQQ", "VUG", "SPY"],
            "model_version": [MODEL_VERSION] * 5,
            "score": [99.0, 2.0, 0.7, 0.9, 9.0],
            "predicted_return": [0.02, 0.01, 0.004, 0.012, 0.03],
            "rank": [1, 2, 2, 1, 3],
            "confidence": [0.9, 0.8, 0.7, 0.88, 0.95],
            "signal_bucket": ["top", "top", "top", "top", "middle"],
            "created_at": ["2026-05-08T12:00:00Z"] * 5,
        }
    )


def test_preview_selects_latest_top_bucket_and_ranks_by_score() -> None:
    preview = preview_current_model_signal(MODEL_VERSION, frame=_preview_frame())

    assert preview["latest_signal_date"] == "2026-05-08"
    assert preview["row_count_latest_date"] == 3
    assert preview["universe_symbol_count"] == 3
    assert preview["signal_bucket_filter"] == ["top"]
    assert preview["selected_symbols"] == ["VUG"]
    selected = preview["selected_rows"][0]
    assert selected["symbol"] == "VUG"
    assert selected["score"] == 0.9
    assert selected["rank"] == 1
    assert selected["predicted_return"] == 0.012
    assert selected["confidence"] == 0.88
    assert selected["signal_bucket"] == "top"


def test_preview_reads_ready_manifest_and_surfaces_warnings(tmp_path) -> None:
    version_dir = tmp_path / f"model_version={MODEL_VERSION}"
    version_dir.mkdir()
    _preview_frame().to_csv(version_dir / "signals.csv", index=False)
    (version_dir / "model_signal_manifest.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "feature_set_version": "default_features_v1",
                "label_horizon_days": 20,
                "latest_signal_date": "2026-05-08",
                "row_count": 162,
                "symbol_count": 27,
                "export_created_at": "2026-05-08T23:00:00Z",
                "candidate_id": (
                    "baseline:linear_smooth10_margin002:"
                    "linear_regression:1:42:10:0.002"
                ),
                "artifact_path": "/private/research/signals.parquet",
                "status": "ready",
                "warnings": ["late merge reviewed"],
            }
        ),
        encoding="utf-8",
    )

    preview = preview_current_model_signal(MODEL_VERSION, data_path=str(tmp_path))

    assert preview["selected_symbols"] == ["VUG"]
    assert preview["manifest_status"] == "ready"
    assert preview["manifest_warnings"] == ["late merge reviewed"]
    assert preview["export_created_at"] == "2026-05-08T23:00:00Z"
    assert preview["generated_at"] == "2026-05-08T23:00:00Z"
    assert "artifact_path" not in preview["manifest"]
    assert preview["manifest"]["candidate_id"].startswith("baseline:")


def test_preview_works_without_manifest(tmp_path) -> None:
    version_dir = tmp_path / f"model_version={MODEL_VERSION}"
    version_dir.mkdir()
    _preview_frame().to_csv(version_dir / "signals.csv", index=False)

    preview = preview_current_model_signal(MODEL_VERSION, data_path=str(tmp_path))

    assert preview["selected_symbols"] == ["VUG"]
    assert preview["manifest"] is None
    assert preview["manifest_warnings"] == []


def test_preview_rejects_manifest_that_is_not_ready(tmp_path) -> None:
    version_dir = tmp_path / f"model_version={MODEL_VERSION}"
    version_dir.mkdir()
    _preview_frame().to_csv(version_dir / "signals.csv", index=False)
    (version_dir / "model_signal_manifest.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "latest_signal_date": "2026-05-08",
                "status": "draft",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelSignalPreviewInvalidError, match="status must be ready"):
        preview_current_model_signal(MODEL_VERSION, data_path=str(tmp_path))


def test_preview_missing_artifact_raises_controlled_error(tmp_path) -> None:
    missing_path = tmp_path / "missing"

    with pytest.raises(ModelSignalPreviewNotFoundError) as exc_info:
        preview_current_model_signal(MODEL_VERSION, data_path=str(missing_path))

    assert exc_info.value.code == "MODEL_SIGNAL_ARTIFACT_NOT_FOUND"
    assert str(missing_path) not in str(exc_info.value)
