from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_FIXTURE = REPO_ROOT / "tests/fixtures/model_signals/valid_signals.csv"


def run_validator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/validate_model_signal_export.py", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_validate_model_signal_export_valid_csv_exits_zero() -> None:
    result = run_validator("--path", str(VALID_FIXTURE))

    assert result.returncode == 0
    assert "status: valid" in result.stdout
    assert "rows: 3" in result.stdout
    assert "date_min: 2024-01-31" in result.stdout
    assert "date_max: 2024-02-29" in result.stdout
    assert "symbol_count: 3" in result.stdout
    assert "symbols: QQQ, SPY, TLT" in result.stdout
    assert "model_versions: etf-ranker-21d-v1" in result.stdout
    assert "missing_required_columns: none" in result.stdout
    assert "duplicate_count: 0" in result.stdout


def test_validate_model_signal_export_missing_column_exits_nonzero(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    pd.read_csv(VALID_FIXTURE).drop(columns=["score"]).to_csv(path, index=False)

    result = run_validator("--path", str(path))

    assert result.returncode == 1
    assert "status: invalid" in result.stdout
    assert "missing_required_columns: score" in result.stdout
    assert "missing required columns: score" in result.stderr


def test_validate_model_signal_export_duplicate_exits_nonzero(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    frame = pd.read_csv(VALID_FIXTURE)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    frame.to_csv(path, index=False)

    result = run_validator("--path", str(path))

    assert result.returncode == 1
    assert "status: invalid" in result.stdout
    assert "duplicate_count: 2" in result.stdout
    assert "duplicate date/symbol/model_version" in result.stderr


def test_validate_model_signal_export_model_version_filter(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    frame = pd.read_csv(VALID_FIXTURE)
    other = frame.assign(model_version="etf-ranker-21d-v2", score=9.0)
    pd.concat([frame, other], ignore_index=True).to_csv(path, index=False)

    result = run_validator(
        "--path",
        str(path),
        "--model-version",
        "etf-ranker-21d-v2",
    )

    assert result.returncode == 0
    assert "rows: 3" in result.stdout
    assert "model_versions: etf-ranker-21d-v2" in result.stdout


def test_validate_model_signal_export_does_not_require_s3(tmp_path) -> None:
    path = tmp_path / "signals.csv"
    pd.read_csv(VALID_FIXTURE).to_csv(path, index=False)

    result = run_validator("--path", str(path), "--start-date", "2024-02-01")

    assert result.returncode == 0
    assert "rows: 1" in result.stdout
    assert "date_min: 2024-02-29" in result.stdout
