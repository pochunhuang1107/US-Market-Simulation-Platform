from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID
from urllib.parse import urlparse

import boto3

from market_simulator.db.enums import ArtifactStorageType
from market_simulator.platform.services.artifact_manifest import is_s3_uri
from market_simulator.settings import get_settings


@dataclass
class ArtifactWriteResult:
    storage_type: str
    artifact_dir: str
    artifact_root_uri: str
    manifest_json: dict
    summary_json: dict | None = None


class ArtifactStore(Protocol):
    def prepare_run_directory(self, run_id: UUID | str) -> Path: ...
    def finalize_simulation_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult: ...
    def finalize_sweep_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult: ...
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
            "trade_signal_snapshots": str(run_dir / "trade_signal_snapshots.json"),
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

    def finalize_sweep_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult:
        run_dir = self.base_dir / "runs" / str(run_id)
        manifest = {
            "sweep_summary": str(run_dir / "sweep_summary.json"),
            "sweep_results": str(run_dir / "sweep_results.csv"),
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
        s3_client: Any | None = None,
    ):
        settings = get_settings()
        self.bucket = bucket or settings.artifact_s3_bucket
        self.prefix = (prefix or settings.artifact_s3_prefix).strip("/")
        self.region = region or settings.artifact_s3_region
        self.local_base_dir = Path(local_base_dir or settings.artifacts_dir)
        self.presign_ttl_seconds = settings.artifact_presign_ttl_seconds

        if s3_client is not None:
            self.s3 = s3_client
        else:
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
            "trade_signal_snapshots": "trade_signal_snapshots.json",
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

    def finalize_sweep_artifacts(self, run_id: UUID | str) -> ArtifactWriteResult:
        run_dir = self.local_base_dir / "runs" / str(run_id)
        s3_root_prefix = f"{self.prefix}/runs/{run_id}"
        artifact_root_uri = f"s3://{self.bucket}/{s3_root_prefix}"

        summary_json = self._rewrite_sweep_artifacts_for_s3(
            run_dir=run_dir,
            artifact_root_uri=artifact_root_uri,
        )

        expected_files = {
            "sweep_summary": "sweep_summary.json",
            "sweep_results": "sweep_results.csv",
        }

        manifest = {}
        for manifest_key, filename in expected_files.items():
            path = run_dir / filename
            if not path.exists() or not path.is_file():
                continue

            key = f"{s3_root_prefix}/{filename}"
            self.s3.upload_file(str(path), self.bucket, key)
            manifest[manifest_key] = f"s3://{self.bucket}/{key}"

        for path in self._iter_variant_artifact_files(run_dir):
            key = f"{s3_root_prefix}/{path.relative_to(run_dir).as_posix()}"
            self.s3.upload_file(str(path), self.bucket, key)

        return ArtifactWriteResult(
            storage_type=ArtifactStorageType.S3,
            artifact_dir=str(run_dir),
            artifact_root_uri=artifact_root_uri,
            manifest_json=manifest,
            summary_json=summary_json,
        )

    def _iter_variant_artifact_files(self, run_dir: Path):
        variant_root = run_dir / "variants"
        if not variant_root.exists() or not variant_root.is_dir():
            return

        for path in variant_root.rglob("*"):
            if path.is_file():
                yield path

    def _rewrite_sweep_artifacts_for_s3(
        self,
        *,
        run_dir: Path,
        artifact_root_uri: str,
    ) -> dict | None:
        summary_path = run_dir / "sweep_summary.json"
        summary_json = None
        if summary_path.exists() and summary_path.is_file():
            summary_json = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary_json, dict):
                self._rewrite_summary_variant_artifact_dirs(
                    summary_json,
                    run_dir=run_dir,
                    artifact_root_uri=artifact_root_uri,
                )
                summary_path.write_text(
                    json.dumps(summary_json, indent=2, default=str),
                    encoding="utf-8",
                )

        results_path = run_dir / "sweep_results.csv"
        if results_path.exists() and results_path.is_file():
            self._rewrite_sweep_results_csv(
                results_path,
                run_dir=run_dir,
                artifact_root_uri=artifact_root_uri,
            )

        return summary_json if isinstance(summary_json, dict) else None

    def _rewrite_summary_variant_artifact_dirs(
        self,
        summary_json: dict,
        *,
        run_dir: Path,
        artifact_root_uri: str,
    ) -> None:
        results = summary_json.get("results")
        if isinstance(results, list):
            for row in results:
                if isinstance(row, dict):
                    self._rewrite_variant_row_artifact_dir(
                        row,
                        run_dir=run_dir,
                        artifact_root_uri=artifact_root_uri,
                    )

        best_variant = summary_json.get("best_variant")
        if isinstance(best_variant, dict):
            self._rewrite_variant_row_artifact_dir(
                best_variant,
                run_dir=run_dir,
                artifact_root_uri=artifact_root_uri,
            )

    def _rewrite_sweep_results_csv(
        self,
        results_path: Path,
        *,
        run_dir: Path,
        artifact_root_uri: str,
    ) -> None:
        with results_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        if not fieldnames:
            return

        for row in rows:
            self._rewrite_variant_row_artifact_dir(
                row,
                run_dir=run_dir,
                artifact_root_uri=artifact_root_uri,
                include_artifact_root_uri=False,
            )

        with results_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _rewrite_variant_row_artifact_dir(
        self,
        row: dict,
        *,
        run_dir: Path,
        artifact_root_uri: str,
        include_artifact_root_uri: bool = True,
    ) -> None:
        current_artifact_dir = row.get("artifact_dir")
        s3_artifact_dir = self._s3_variant_artifact_dir(
            current_artifact_dir,
            variant_id=row.get("variant_id"),
            run_dir=run_dir,
            artifact_root_uri=artifact_root_uri,
        )
        if s3_artifact_dir is None:
            if isinstance(current_artifact_dir, str) and current_artifact_dir.strip():
                row["artifact_dir"] = None
            return

        row["artifact_dir"] = s3_artifact_dir
        if include_artifact_root_uri:
            row["artifact_root_uri"] = s3_artifact_dir

    def _s3_variant_artifact_dir(
        self,
        artifact_dir: Any,
        *,
        variant_id: Any,
        run_dir: Path,
        artifact_root_uri: str,
    ) -> str | None:
        if isinstance(artifact_dir, str) and artifact_dir.strip():
            artifact_dir = artifact_dir.strip()
            if is_s3_uri(artifact_dir):
                return artifact_dir.rstrip("/")

            try:
                relative_path = Path(artifact_dir).resolve(strict=False).relative_to(
                    run_dir.resolve(strict=False)
                )
                return f"{artifact_root_uri}/{relative_path.as_posix()}"
            except ValueError:
                variant_dir = self._find_variant_dir(run_dir, variant_id)
                if variant_dir is not None:
                    return f"{artifact_root_uri}/{variant_dir.relative_to(run_dir).as_posix()}"
                return f"{artifact_root_uri}/variants/{Path(artifact_dir).name}"

        variant_dir = self._find_variant_dir(run_dir, variant_id)
        if variant_dir is None:
            return None

        return f"{artifact_root_uri}/{variant_dir.relative_to(run_dir).as_posix()}"

    def _find_variant_dir(self, run_dir: Path, variant_id: Any) -> Path | None:
        if not isinstance(variant_id, str) or not variant_id.strip():
            return None

        variant_root = run_dir / "variants"
        if not variant_root.exists() or not variant_root.is_dir():
            return None

        variant_id = variant_id.strip()
        for child in variant_root.iterdir():
            if child.is_dir() and (
                child.name == variant_id or child.name.endswith(f"_{variant_id}")
            ):
                return child

        return None

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
