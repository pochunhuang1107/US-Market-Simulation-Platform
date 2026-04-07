from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID
from urllib.parse import urlparse

import boto3

from market_simulator.db.enums import ArtifactStorageType
from market_simulator.settings import get_settings


@dataclass
class ArtifactWriteResult:
    storage_type: str
    artifact_dir: str
    artifact_root_uri: str
    manifest_json: dict


class ArtifactStore(Protocol):
    def prepare_run_directory(self, run_id: UUID | str) -> Path: ...
    def finalize_simulation_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult: ...
    def generate_download_url(self, artifact_uri: str) -> str: ...


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

    def generate_download_url(self, artifact_uri: str) -> str:
        return artifact_uri


class S3ArtifactStore:
    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str | None = None,
        region: str | None = None,
        local_base_dir: str | None = None,
    ):
        settings = get_settings()
        self.bucket = bucket or settings.artifact_s3_bucket
        self.prefix = (prefix or settings.artifact_s3_prefix).strip("/")
        self.region = region or settings.artifact_s3_region
        self.local_base_dir = Path(local_base_dir or settings.artifacts_dir)
        self.presign_ttl_seconds = settings.artifact_presign_ttl_seconds
        
        from botocore.config import Config

        self.s3 = boto3.client(
            "s3",
            region_name=self.region,
            config=Config(signature_version="s3v4"),
        )

        if not self.bucket:
            raise ValueError("ARTIFACT_S3_BUCKET is required when using S3 artifact storage")

    def prepare_run_directory(self, run_id: UUID | str) -> Path:
        run_dir = self.local_base_dir / "runs" / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def finalize_simulation_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult:
        run_dir = self.local_base_dir / "runs" / str(run_id)
        s3_root_prefix = f"{self.prefix}/runs/{run_id}"

        expected_files = {
            "summary": "summary.json",
            "sleeve_summary": "sleeve_summary.json",
            "yearly_report": "yearly_report.csv",
            "trade_log": "trade_log.csv",
            "timeline": "timeline.csv",
            "events": "events.csv",
            "monthly_returns": "monthly_returns.csv",
            "report_bundle": "report_bundle.json",
        }

        manifest = {}
        for manifest_key, filename in expected_files.items():
            path = run_dir / filename
            if not path.exists() or not path.is_file():
                continue

            key = f"{s3_root_prefix}/{filename}"
            self.s3.upload_file(str(path), self.bucket, key)
            manifest[manifest_key] = f"s3://{self.bucket}/{key}"

        artifact_root_uri = f"s3://{self.bucket}/{s3_root_prefix}"

        return ArtifactWriteResult(
            storage_type=ArtifactStorageType.S3,
            artifact_dir=str(run_dir),
            artifact_root_uri=artifact_root_uri,
            manifest_json=manifest,
        )

    def generate_download_url(self, artifact_uri: str) -> str:
        parsed = urlparse(artifact_uri)
        if parsed.scheme != "s3":
            return artifact_uri

        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=self.presign_ttl_seconds,
        )


def build_artifact_store() -> ArtifactStore:
    settings = get_settings()
    backend = (settings.artifact_storage_backend or "LOCAL").upper()

    if backend == "S3":
        return S3ArtifactStore()

    return LocalArtifactStore()