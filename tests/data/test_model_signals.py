from __future__ import annotations

import pandas as pd
import pytest

from market_simulator.data.model_signals import (
    ModelSignalDataset,
    ModelSignalRepository,
    load_model_signal_frame,
    validate_model_signal_frame,
)


SUPPORTED_SYMBOLS = ("QQQ", "SPY", "TLT")


def _valid_signal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-31", "2024-01-31", "2024-02-29"],
            "symbol": ["qqq", "SPY", "TLT"],
            "model_version": ["etf-ranker-v1", "etf-ranker-v1", "etf-ranker-v1"],
            "score": [0.72, 0.41, -0.12],
            "predicted_return": [0.018, 0.009, -0.004],
            "rank": [1, 2, 3],
            "confidence": [0.83, 0.61, 0.55],
            "signal_bucket": ["top", "middle", "bottom"],
        }
    )


def test_valid_signal_frame_passes() -> None:
    validated = validate_model_signal_frame(
        _valid_signal_frame(),
        supported_symbols=SUPPORTED_SYMBOLS,
    )

    assert list(validated["symbol"]) == ["QQQ", "SPY", "TLT"]
    assert pd.api.types.is_datetime64_any_dtype(validated["date"])
    assert list(validated["score"]) == [0.72, 0.41, -0.12]


def test_optional_fields_are_accepted() -> None:
    frame = _valid_signal_frame()
    frame["feature_set_version"] = "features-v4"
    frame["label_horizon_days"] = 21
    frame["created_at"] = "2025-01-02T03:04:05Z"

    dataset = ModelSignalDataset.from_frame(
        frame,
        supported_symbols=SUPPORTED_SYMBOLS,
    )

    assert dataset.symbols == ("QQQ", "SPY", "TLT")
    assert dataset.model_versions == ("etf-ranker-v1",)


def test_missing_required_column_fails() -> None:
    frame = _valid_signal_frame().drop(columns=["score"])

    with pytest.raises(ValueError, match="missing required columns: score"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_unsupported_symbol_fails() -> None:
    frame = _valid_signal_frame()
    frame.loc[0, "symbol"] = "AAPL"

    with pytest.raises(ValueError, match="unsupported ETF symbols: AAPL"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_duplicate_date_symbol_model_version_fails() -> None:
    frame = _valid_signal_frame()
    frame.loc[1, "symbol"] = "QQQ"

    with pytest.raises(ValueError, match="duplicate date/symbol/model_version"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_invalid_date_fails() -> None:
    frame = _valid_signal_frame()
    frame.loc[0, "date"] = "not-a-date"

    with pytest.raises(ValueError, match="date values must parse correctly"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_nonnumeric_score_fails() -> None:
    frame = _valid_signal_frame()
    frame["score"] = frame["score"].astype("object")
    frame.loc[0, "score"] = "strong buy"

    with pytest.raises(ValueError, match="score must be numeric"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_nonnumeric_rank_fails_when_present() -> None:
    frame = _valid_signal_frame()
    frame["rank"] = frame["rank"].astype("object")
    frame.loc[0, "rank"] = "first"

    with pytest.raises(ValueError, match="rank must be numeric"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_confidence_outside_unit_interval_fails() -> None:
    frame = _valid_signal_frame()
    frame.loc[0, "confidence"] = 1.25

    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_empty_model_version_fails() -> None:
    frame = _valid_signal_frame()
    frame.loc[0, "model_version"] = " "

    with pytest.raises(ValueError, match="model_version must be present"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_future_label_columns_are_rejected() -> None:
    frame = _valid_signal_frame()
    frame["future_return_21d"] = [0.01, -0.02, 0.03]

    with pytest.raises(ValueError, match="lookahead label columns"):
        validate_model_signal_frame(frame, supported_symbols=SUPPORTED_SYMBOLS)


def test_load_model_signal_frame_reads_local_parquet_without_s3(tmp_path) -> None:
    path = tmp_path / "signals.parquet"
    _valid_signal_frame().to_parquet(path, index=False)

    validated = load_model_signal_frame(path, supported_symbols=SUPPORTED_SYMBOLS)

    assert len(validated) == 3
    assert set(validated["symbol"]) == {"QQQ", "SPY", "TLT"}


def test_load_model_signal_frame_reads_local_csv(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    _valid_signal_frame().to_csv(path, index=False)

    validated = load_model_signal_frame(path, supported_symbols=SUPPORTED_SYMBOLS)

    assert len(validated) == 3
    assert set(validated["symbol"]) == {"QQQ", "SPY", "TLT"}


def test_repository_builds_project_path_without_s3() -> None:
    repository = ModelSignalRepository("/tmp/curated/model_signals")

    assert (
        repository.path_for_model_version("etf-ranker-v1").as_posix()
        == "/tmp/curated/model_signals/model_version=etf-ranker-v1/signals.parquet"
    )


def test_repository_loads_valid_csv_and_filters_model_version(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    frame = pd.concat(
        [
            _valid_signal_frame(),
            _valid_signal_frame().assign(model_version="etf-ranker-v2", score=9.0),
        ],
        ignore_index=True,
    )
    frame.to_csv(path, index=False)

    loaded = ModelSignalRepository(
        path,
        supported_symbols=SUPPORTED_SYMBOLS,
    ).load(model_version="etf-ranker-v2")

    assert len(loaded) == 3
    assert loaded["model_version"].unique().tolist() == ["etf-ranker-v2"]
    assert loaded["score"].tolist() == [9.0, 9.0, 9.0]


def test_repository_loads_valid_parquet_and_filters_universe(tmp_path) -> None:
    path = tmp_path / "signals.parquet"
    _valid_signal_frame().to_parquet(path, index=False)

    loaded = ModelSignalRepository(
        path,
        supported_symbols=SUPPORTED_SYMBOLS,
    ).load(universe=["QQQ", "SPY"])

    assert loaded["symbol"].tolist() == ["QQQ", "SPY"]


def test_repository_date_range_filter_excludes_future_rows(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    frame = pd.concat(
        [
            _valid_signal_frame(),
            pd.DataFrame(
                {
                    "date": ["2024-03-29"],
                    "symbol": ["QQQ"],
                    "model_version": ["etf-ranker-v1"],
                    "score": [99.0],
                }
            ),
        ],
        ignore_index=True,
    )
    frame.to_csv(path, index=False)

    loaded = ModelSignalRepository(
        path,
        supported_symbols=SUPPORTED_SYMBOLS,
    ).load(
        model_version="etf-ranker-v1",
        start_date="2024-02-01",
        end_date="2024-02-29",
    )

    assert loaded["date"].dt.strftime("%Y-%m-%d").tolist() == ["2024-02-29"]
    assert loaded["symbol"].tolist() == ["TLT"]


def test_repository_missing_required_columns_fails(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    _valid_signal_frame().drop(columns=["score"]).to_csv(path, index=False)

    with pytest.raises(ValueError, match="missing required columns: score"):
        ModelSignalRepository(path, supported_symbols=SUPPORTED_SYMBOLS).load()


def test_repository_unsupported_symbols_fail(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    frame = _valid_signal_frame()
    frame.loc[0, "symbol"] = "AAPL"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="unsupported ETF symbols: AAPL"):
        ModelSignalRepository(path, supported_symbols=SUPPORTED_SYMBOLS).load()


def test_repository_duplicate_date_symbol_model_version_fails(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    frame = _valid_signal_frame()
    frame.loc[1, "symbol"] = "QQQ"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="duplicate date/symbol/model_version"):
        ModelSignalRepository(path, supported_symbols=SUPPORTED_SYMBOLS).load()


def test_repository_missing_path_gives_controlled_error(tmp_path) -> None:
    path = tmp_path / "missing-signals.csv"

    with pytest.raises(ValueError, match="Model signal path does not exist"):
        ModelSignalRepository(path, supported_symbols=SUPPORTED_SYMBOLS).load()
