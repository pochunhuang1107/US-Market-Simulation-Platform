from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_preflight(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/beta_preflight.py", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )


def valid_backend_values() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql+psycopg://db_user:db_password@db.example.com:5432/app",
        "ENV": "beta",
        "AUTH_MODE": "oidc",
        "OIDC_JWKS_URL": "https://issuer.example.com/.well-known/jwks.json",
        "OIDC_ISSUER": "https://issuer.example.com/",
        "OIDC_AUDIENCE": "market-simulator-api",
        "ENABLE_DEV_ADMIN_OVERRIDE": "false",
        "MARKET_DATA_PATH": "s3://market-data/curated/etf_daily_prices/**/*.parquet",
        "ETF_METADATA_S3_URI": "s3://market-data/curated/reference/etf_symbol_metadata/data.parquet",
        "REFERENCE_SERIES_DATA_PATH": "s3://market-data/curated/reference_series",
        "REFERENCE_SERIES_METADATA_S3_URI": (
            "s3://market-data/curated/reference/reference_series_metadata/data.parquet"
        ),
        "ARTIFACT_STORAGE_BACKEND": "S3",
        "ARTIFACT_S3_BUCKET": "beta-artifacts",
        "ARTIFACT_S3_PREFIX": "artifacts",
        "ARTIFACT_S3_REGION": "us-west-2",
    }


def valid_frontend_values() -> dict[str, str]:
    return {
        "VITE_AUTH_PROVIDER": "auth0",
        "VITE_AUTH0_DOMAIN": "issuer.example.com",
        "VITE_AUTH0_CLIENT_ID": "spa-client-id",
        "VITE_AUTH0_AUDIENCE": "market-simulator-api",
    }


def test_committed_beta_templates_pass_preflight():
    result = run_preflight()

    assert result.returncode == 0
    assert "PASS beta preflight" in result.stdout


def test_preflight_rejects_dev_auth_and_local_artifacts_for_beta(tmp_path):
    backend = valid_backend_values()
    backend["AUTH_MODE"] = "dev"
    backend["ARTIFACT_STORAGE_BACKEND"] = "LOCAL"
    backend["ARTIFACTS_DIR"] = "/tmp/artifacts"
    backend.pop("ARTIFACT_S3_BUCKET")
    backend.pop("ARTIFACT_S3_PREFIX")
    backend.pop("ARTIFACT_S3_REGION")

    backend_path = tmp_path / "backend.env"
    frontend_path = tmp_path / "frontend.env"
    write_env(backend_path, backend)
    write_env(frontend_path, valid_frontend_values())

    result = run_preflight(
        "--backend-env",
        str(backend_path),
        "--frontend-env",
        str(frontend_path),
    )

    assert result.returncode == 1
    assert "Protected ENV must not use dev/local/test AUTH_MODE." in result.stderr
    assert "Protected beta/production should use ARTIFACT_STORAGE_BACKEND=S3." in result.stderr


def test_preflight_rejects_missing_frontend_auth0_vars(tmp_path):
    backend_path = tmp_path / "backend.env"
    frontend_path = tmp_path / "frontend.env"
    write_env(backend_path, valid_backend_values())
    write_env(frontend_path, {"VITE_AUTH_PROVIDER": "auth0"})

    result = run_preflight(
        "--backend-env",
        str(backend_path),
        "--frontend-env",
        str(frontend_path),
    )

    assert result.returncode == 1
    assert "VITE_AUTH0_DOMAIN" in result.stderr
    assert "VITE_AUTH0_CLIENT_ID" in result.stderr
    assert "VITE_AUTH0_AUDIENCE" in result.stderr


def test_preflight_requires_openai_key_only_when_provider_is_openai(tmp_path):
    backend = valid_backend_values()
    backend["STRATEGY_BUILDER_PROVIDER"] = "openai"
    backend_path = tmp_path / "backend.env"
    frontend_path = tmp_path / "frontend.env"
    write_env(backend_path, backend)
    write_env(frontend_path, valid_frontend_values())

    result = run_preflight(
        "--backend-env",
        str(backend_path),
        "--frontend-env",
        str(frontend_path),
    )

    assert result.returncode == 1
    assert "OPENAI_API_KEY is required only when STRATEGY_BUILDER_PROVIDER=openai." in result.stderr

    backend["STRATEGY_BUILDER_PROVIDER"] = "deterministic"
    backend["OPENAI_API_KEY"] = ""
    write_env(backend_path, backend)

    result = run_preflight(
        "--backend-env",
        str(backend_path),
        "--frontend-env",
        str(frontend_path),
    )

    assert result.returncode == 0

    backend["STRATEGY_BUILDER_PROVIDER"] = "hybrid"
    backend["OPENAI_API_KEY"] = ""
    write_env(backend_path, backend)

    result = run_preflight(
        "--backend-env",
        str(backend_path),
        "--frontend-env",
        str(frontend_path),
    )

    assert result.returncode == 0


def test_preflight_does_not_print_secret_values(tmp_path):
    backend = valid_backend_values()
    backend["DATABASE_URL"] = (
        "postgresql+psycopg://private_user:super-secret-password@db.example.com:5432/app"
    )
    backend.pop("OIDC_JWKS_URL")
    frontend = valid_frontend_values()
    frontend["VITE_AUTH0_CLIENT_ID"] = "secret-client-id"

    backend_path = tmp_path / "backend.env"
    frontend_path = tmp_path / "frontend.env"
    write_env(backend_path, backend)
    write_env(frontend_path, frontend)

    result = run_preflight(
        "--backend-env",
        str(backend_path),
        "--frontend-env",
        str(frontend_path),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "super-secret-password" not in output
    assert "private_user" not in output
    assert "secret-client-id" not in output
