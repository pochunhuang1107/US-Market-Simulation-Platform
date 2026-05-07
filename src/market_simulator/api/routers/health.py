from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from market_simulator.db.session import get_db
from market_simulator.repositories.runs import get_run_queue_health
from market_simulator.settings import Settings, get_settings

router = APIRouter()

CheckResult = dict[str, Any]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/readiness")
def readiness(db: Session = Depends(get_db)):
    settings = get_settings()
    checks = {
        "app": _app_check(settings),
        "database": _database_check(db, settings),
        "auth": _auth_check(settings),
        "artifact_storage": _artifact_storage_check(settings),
        "data_paths": _data_paths_check(settings),
        "supported_symbols": _supported_symbols_check(settings),
        "run_queue": _run_queue_check(db, settings),
    }
    return {
        "overall_status": _overall_status(checks),
        "checks": checks,
    }


def _app_check(settings: Settings) -> CheckResult:
    return {
        "status": "ready",
        "message": "Application is running.",
        "environment": settings.normalized_env,
        "auth_mode": settings.resolved_auth_mode,
    }


def _database_check(db: Session, settings: Settings) -> CheckResult:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        return {
            "status": "not_ready",
            "message": "Database connectivity check failed.",
            "database_backend": _database_backend(settings),
            "error_type": exc.__class__.__name__,
        }

    return {
        "status": "ready",
        "message": "Database connectivity check passed.",
        "database_backend": _database_backend(settings),
    }


def _auth_check(settings: Settings) -> CheckResult:
    auth_mode = settings.resolved_auth_mode
    if settings.is_dev_auth_enabled:
        return {
            "status": "ready",
            "message": "Development auth is enabled for this environment.",
            "mode": auth_mode,
            "dev_auth_enabled": True,
        }

    if settings.is_oidc_auth_enabled:
        jwks_configured = _is_configured(settings.oidc_jwks_url)
        issuer_configured = _is_configured(settings.oidc_issuer)
        audience_configured = _is_configured(settings.oidc_audience)
        return {
            "status": "ready" if jwks_configured else "not_ready",
            "message": (
                "OIDC auth is configured."
                if jwks_configured
                else "OIDC auth requires OIDC_JWKS_URL."
            ),
            "mode": auth_mode,
            "oidc_jwks_url_configured": jwks_configured,
            "oidc_issuer_configured": issuer_configured,
            "oidc_audience_configured": audience_configured,
        }

    return {
        "status": "not_ready",
        "message": "Authentication is required but no provider is configured.",
        "mode": auth_mode,
        "dev_auth_enabled": False,
        "oidc_jwks_url_configured": _is_configured(settings.oidc_jwks_url),
        "oidc_issuer_configured": _is_configured(settings.oidc_issuer),
        "oidc_audience_configured": _is_configured(settings.oidc_audience),
    }


def _artifact_storage_check(settings: Settings) -> CheckResult:
    backend = (settings.artifact_storage_backend or "LOCAL").strip().upper()
    if backend == "S3":
        bucket_configured = _is_configured(settings.artifact_s3_bucket)
        prefix_configured = _is_configured(settings.artifact_s3_prefix)
        region_configured = _is_configured(settings.artifact_s3_region)
        ready = bucket_configured and prefix_configured and region_configured
        return {
            "status": "ready" if ready else "not_ready",
            "message": (
                "S3 artifact storage is configured."
                if ready
                else (
                    "S3 artifact storage requires ARTIFACT_S3_BUCKET, "
                    "ARTIFACT_S3_PREFIX, and ARTIFACT_S3_REGION."
                )
            ),
            "backend": backend,
            "bucket_configured": bucket_configured,
            "prefix_configured": prefix_configured,
            "region_configured": region_configured,
        }

    if backend != "LOCAL":
        return {
            "status": "not_ready",
            "message": "Unsupported artifact storage backend.",
            "backend": backend,
        }

    path_configured = bool(settings.artifacts_dir)
    creatable = _path_is_creatable(settings.artifacts_dir)
    local_ready = path_configured and creatable
    if local_ready and settings.is_protected_env:
        return {
            "status": "warning",
            "message": "Local artifact storage is available but S3 is preferred for beta/production.",
            "backend": backend,
            "path_configured": path_configured,
            "path_creatable": creatable,
            "s3_preferred": True,
        }

    return {
        "status": "ready" if local_ready else "not_ready",
        "message": (
            "Local artifact storage directory is available."
            if local_ready
            else "Local artifact storage requires a creatable ARTIFACTS_DIR."
        ),
        "backend": backend,
        "path_configured": path_configured,
        "path_creatable": creatable,
    }


def _data_paths_check(settings: Settings) -> CheckResult:
    paths = {
        "market_data_path": _path_config_status(settings.market_data_path),
        "etf_metadata_s3_uri": _path_config_status(settings.etf_metadata_s3_uri),
        "reference_series_data_path": _path_config_status(
            settings.reference_series_data_path
        ),
        "reference_series_metadata_s3_uri": _path_config_status(
            settings.reference_series_metadata_s3_uri
        ),
    }
    status = _overall_status(paths)
    message = (
        "Market and reference-series data paths are configured."
        if status == "ready"
        else "One or more market/reference-series data paths are missing or placeholders."
    )
    return {
        "status": status,
        "message": message,
        "paths": paths,
    }


def _supported_symbols_check(settings: Settings) -> CheckResult:
    etf_count = len(settings.supported_etf_symbols)
    reference_series_count = len(settings.supported_reference_series_symbols)
    ready = etf_count > 0 and reference_series_count > 0
    return {
        "status": "ready" if ready else "not_ready",
        "message": (
            "Supported symbol universes are configured."
            if ready
            else "Supported ETF and reference-series symbols must be configured."
        ),
        "etf_symbol_count": etf_count,
        "reference_series_symbol_count": reference_series_count,
    }


def _run_queue_check(db: Session, settings: Settings) -> CheckResult:
    try:
        queue_health = get_run_queue_health(
            db,
            running_stale_seconds=settings.running_stale_seconds,
        )
    except Exception as exc:
        return {
            "status": "not_ready",
            "message": "Run queue aggregate check failed.",
            "error_type": exc.__class__.__name__,
        }

    status = "ready"
    message = "Run queue has no stale running runs or suspiciously old queued runs."
    oldest_queued_age_seconds = queue_health["oldest_queued_age_seconds"]

    if queue_health["stale_running_count"] > 0:
        status = "not_ready"
        message = "One or more running runs appear stale."
    elif (
        oldest_queued_age_seconds is not None
        and oldest_queued_age_seconds > settings.queue_oldest_warning_seconds
    ):
        status = "warning"
        message = "Old queued runs may indicate the worker is not claiming work."

    return {
        "status": status,
        "message": message,
        **queue_health,
        "queue_oldest_warning_seconds": settings.queue_oldest_warning_seconds,
        "running_stale_seconds": settings.running_stale_seconds,
        "stale_recovery_available": True,
    }


def _path_config_status(value: str | None) -> CheckResult:
    configured = _is_configured(value)
    placeholder = _is_placeholder(value)
    status = "ready"
    if not configured:
        status = "not_ready"
    elif placeholder:
        status = "warning"
    return {
        "status": status,
        "configured": configured,
        "placeholder": placeholder,
    }


def _overall_status(checks: dict[str, CheckResult]) -> str:
    statuses = {check["status"] for check in checks.values()}
    if "not_ready" in statuses:
        return "not_ready"
    if "warning" in statuses:
        return "warning"
    return "ready"


def _database_backend(settings: Settings) -> str:
    try:
        return make_url(settings.database_url).drivername
    except Exception:
        return "unknown"


def _path_is_creatable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return path.exists() and path.is_dir()


def _is_configured(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return False

    normalized = value.strip().lower()
    placeholder_fragments = (
        "your-",
        "placeholder",
        "change-me",
        "changeme",
        "example",
        "todo",
        "<",
        ">",
    )
    return any(fragment in normalized for fragment in placeholder_fragments)
