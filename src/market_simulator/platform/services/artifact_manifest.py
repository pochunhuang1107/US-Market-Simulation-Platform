from __future__ import annotations

from pathlib import Path


VARIANT_ARTIFACT_FILES = {
    "summary": "summary.json",
    "sleeve_summary": "sleeve_summary.json",
    "yearly_report": "yearly_report.csv",
    "trade_log": "trade_log.csv",
    "timeline": "timeline.csv",
    "events": "events.csv",
    "monthly_returns": "monthly_returns.csv",
    "report_bundle": "report_bundle.json",
}

REQUIRED_VARIANT_ARTIFACT_KEYS = ("timeline", "monthly_returns", "trade_log")


def is_s3_uri(value: str) -> bool:
    return value.strip().startswith("s3://")


def join_artifact_uri(root_uri: str, filename: str) -> str:
    if is_s3_uri(root_uri):
        return f"{root_uri.rstrip('/')}/{filename}"

    return str(Path(root_uri) / filename)


def build_variant_artifact_manifest(
    artifact_dir: str | None,
    *,
    require_local_required_files: bool = False,
) -> dict[str, str] | None:
    if not isinstance(artifact_dir, str) or not artifact_dir.strip():
        return None

    artifact_dir = artifact_dir.strip()
    manifest = {
        key: join_artifact_uri(artifact_dir, filename)
        for key, filename in VARIANT_ARTIFACT_FILES.items()
    }

    if require_local_required_files and not is_s3_uri(artifact_dir):
        if not all(Path(manifest[key]).exists() for key in REQUIRED_VARIANT_ARTIFACT_KEYS):
            return None

    return manifest
