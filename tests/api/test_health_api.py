from __future__ import annotations

from market_simulator import settings as settings_module
from market_simulator.settings import Settings


def _set_readiness_settings(monkeypatch, **overrides):
    values = {
        "env": "local",
        "auth_mode": "dev",
        "market_data_path": "s3://market-data/curated/etf_daily_prices/**/*.parquet",
        "etf_metadata_s3_uri": (
            "s3://market-data/curated/reference/etf_symbol_metadata/data.parquet"
        ),
        "reference_series_data_path": "s3://market-data/curated/reference_series",
        "reference_series_metadata_s3_uri": (
            "s3://market-data/curated/reference/reference_series_metadata/data.parquet"
        ),
    }
    values.update(overrides)
    monkeypatch.setattr(settings_module, "_settings", Settings(**values))


def test_health_remains_simple_liveness(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_database_ready_in_local_mode(client, monkeypatch, tmp_path):
    _set_readiness_settings(monkeypatch, artifacts_dir=tmp_path / "artifacts")

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "ready"
    assert body["checks"]["app"]["environment"] == "local"
    assert body["checks"]["app"]["auth_mode"] == "dev"
    assert body["checks"]["database"]["status"] == "ready"


def test_readiness_warns_for_placeholder_market_data_paths(
    client,
    monkeypatch,
    tmp_path,
):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        market_data_path=(
            "s3://your-market-data-bucket/curated/etf_daily_prices/**/*.parquet"
        ),
    )

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "warning"
    data_paths = body["checks"]["data_paths"]
    assert data_paths["status"] == "warning"
    assert data_paths["paths"]["market_data_path"] == {
        "status": "warning",
        "configured": True,
        "placeholder": True,
    }


def test_readiness_reports_protected_auth_not_ready_without_oidc_config(
    client,
    monkeypatch,
    tmp_path,
):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        env="beta",
        auth_mode="dev",
        oidc_jwks_url=None,
    )

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "not_ready"
    auth = body["checks"]["auth"]
    assert auth["status"] == "not_ready"
    assert auth["mode"] == "required"
    assert auth["message"] == "Authentication is required but no provider is configured."


def test_readiness_reports_oidc_config_present(client, monkeypatch, tmp_path):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        env="beta",
        auth_mode="required",
        oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="market-simulator-api",
    )

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "ready"
    auth = body["checks"]["auth"]
    assert auth["status"] == "ready"
    assert auth["mode"] == "oidc"
    assert auth["oidc_jwks_url_configured"] is True
    assert auth["oidc_issuer_configured"] is True
    assert auth["oidc_audience_configured"] is True


def test_readiness_does_not_leak_secrets(client, monkeypatch, tmp_path):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        database_url=(
            "postgresql+psycopg://db_user:super-secret-password@localhost:5432/db"
        ),
        env="beta",
        auth_mode="required",
        oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="market-simulator-api",
        artifact_storage_backend="S3",
        artifact_s3_bucket="secret-beta-artifacts",
    )

    response = client.get("/health/readiness")

    assert response.status_code == 200
    payload = response.text
    assert "super-secret-password" not in payload
    assert "db_user" not in payload
    assert "postgresql+psycopg://db_user" not in payload
    assert "secret-beta-artifacts" not in payload
    assert "issuer.example.test" not in payload
