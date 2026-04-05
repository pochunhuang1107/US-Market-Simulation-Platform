from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from market_simulator.repositories.runs import (
    get_run,
    mark_run_failed,
    mark_run_running,
    mark_run_succeeded,
)
from market_simulator.repositories.strategies import get_strategy_version
from market_simulator.service import SimulationService
from market_simulator.settings import get_settings


def _build_simulation_artifact_manifest(run_artifact_dir: Path) -> dict:
    return {
        "summary": str(run_artifact_dir / "summary.json"),
        "sleeve_summary": str(run_artifact_dir / "sleeve_summary.json"),
        "yearly_report": str(run_artifact_dir / "yearly_report.csv"),
        "trade_log": str(run_artifact_dir / "trade_log.csv"),
        "timeline": str(run_artifact_dir / "timeline.csv"),
        "events": str(run_artifact_dir / "events.csv"),
        "monthly_returns": str(run_artifact_dir / "monthly_returns.csv"),
        "report_bundle": str(run_artifact_dir / "report_bundle.json"),
    }


def execute_run(db: Session, run_id: str):
    run = get_run(db, run_id)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")

    if run.strategy_version_id is None:
        raise ValueError("Run does not have strategy_version_id")

    strategy_version = get_strategy_version(db, run.strategy_version_id)
    if strategy_version is None:
        raise ValueError(f"Strategy version not found: {run.strategy_version_id}")

    if run.executor_type != "SIMULATION_EXECUTOR":
        raise ValueError(f"Unsupported executor_type for now: {run.executor_type}")

    settings = get_settings()
    run_artifact_dir = Path(settings.artifacts_dir) / "runs" / str(run.id)

    try:
        mark_run_running(db, run)

        service = SimulationService()
        result = service.run_from_config(
            strategy_version.config_json,
            output_dir=run_artifact_dir,
        )

        artifact_manifest = _build_simulation_artifact_manifest(run_artifact_dir)

        mark_run_succeeded(
            db=db,
            run=run,
            summary_json=result.summary,
            artifact_dir=str(run_artifact_dir),
            artifact_manifest_json=artifact_manifest,
        )

        return {
            "run_id": str(run.id),
            "status": "SUCCEEDED",
            "summary": result.summary,
            "artifact_dir": str(run_artifact_dir),
            "artifact_manifest": artifact_manifest,
        }

    except Exception as exc:
        mark_run_failed(db, run, str(exc))
        raise