from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from market_simulator.db.enums import ArtifactStorageType
from market_simulator.settings import get_settings


@dataclass
class ArtifactWriteResult:
    storage_type: str
    artifact_dir: str
    artifact_root_uri: str
    manifest_json: dict


class ArtifactStore(Protocol):
    def prepare_run_directory(self, run_id: UUID | str) -> Path:
        ...

    def finalize_simulation_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult:
        ...


class LocalArtifactStore:
    def __init__(self, base_dir: str | None = None):
        settings = get_settings()
        self.base_dir = Path(base_dir or settings.artifacts_dir)

    def prepare_run_directory(self, run_id: UUID | str) -> Path:
        run_dir = self.base_dir / "runs" / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def finalize_simulation_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult:
        run_dir = self.base_dir / "runs" / str(run_id)
        manifest = {
            "summary": str(run_dir / "summary.json"),
            "sleeve_summary": str(run_dir / "sleeve_summary.json"),
            "yearly_report": str(run_dir / "yearly_report.csv"),
            "trade_log": str(run_dir / "trade_log.csv"),
            "timeline": str(run_dir / "timeline.csv"),
            "events": str(run_dir / "events.csv"),
            "monthly_returns": str(run_dir / "monthly_returns.csv"),
            "report_bundle": str(run_dir / "report_bundle.json"),
        }
        return ArtifactWriteResult(
            storage_type=ArtifactStorageType.LOCAL,
            artifact_dir=str(run_dir),
            artifact_root_uri=str(run_dir),
            manifest_json=manifest,
        )