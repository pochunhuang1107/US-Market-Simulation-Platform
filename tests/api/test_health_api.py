from __future__ import annotations

from datetime import timedelta

from market_simulator.db.enums import ExecutorType, RunStatus, RunType
from market_simulator.repositories.runs import create_run, enqueue_run, utc_now
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
    assert body["checks"]["run_queue"]["status"] == "ready"
    assert body["checks"]["run_queue"]["queued_count"] == 0
    assert body["checks"]["run_queue"]["running_count"] == 0
    assert body["checks"]["run_queue"]["stale_running_count"] == 0


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
        artifact_storage_backend="S3",
        artifact_s3_bucket="beta-artifacts",
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


def test_readiness_reports_s3_artifacts_not_ready_when_required_vars_missing(
    client,
    monkeypatch,
    tmp_path,
):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        env="beta",
        auth_mode="required",
        oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="market-simulator-api",
        artifact_storage_backend="S3",
        artifact_s3_bucket=None,
        artifact_s3_prefix="",
        artifact_s3_region="",
    )

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    artifact_storage = body["checks"]["artifact_storage"]
    assert body["overall_status"] == "not_ready"
    assert artifact_storage["status"] == "not_ready"
    assert artifact_storage["backend"] == "S3"
    assert artifact_storage["bucket_configured"] is False
    assert artifact_storage["prefix_configured"] is False
    assert artifact_storage["region_configured"] is False


def test_readiness_warns_for_local_artifacts_in_protected_env(
    client,
    monkeypatch,
    tmp_path,
):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        env="beta",
        auth_mode="oidc",
        oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="market-simulator-api",
        artifact_storage_backend="LOCAL",
    )

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    artifact_storage = body["checks"]["artifact_storage"]
    assert body["overall_status"] == "warning"
    assert artifact_storage["status"] == "warning"
    assert artifact_storage["backend"] == "LOCAL"
    assert artifact_storage["s3_preferred"] is True


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


def test_readiness_reports_fresh_queued_run_ready(
    client,
    monkeypatch,
    tmp_path,
    db_session,
    create_user,
):
    _set_readiness_settings(monkeypatch, artifacts_dir=tmp_path / "artifacts")
    user = create_user(email="queue-fresh@example.com")
    run = _create_health_run(db_session, user_id=user.id)
    enqueue_run(db_session, run)

    response = client.get("/health/readiness")

    assert response.status_code == 200
    run_queue = response.json()["checks"]["run_queue"]
    assert run_queue["status"] == "ready"
    assert run_queue["queued_count"] == 1
    assert run_queue["pending_count"] == 0
    assert run_queue["running_count"] == 0
    assert run_queue["oldest_queued_age_seconds"] is not None


def test_readiness_warns_for_old_queued_run(
    client,
    monkeypatch,
    tmp_path,
    db_session,
    create_user,
):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        queue_oldest_warning_seconds=60,
    )
    user = create_user(email="queue-old@example.com")
    run = _create_health_run(db_session, user_id=user.id)
    enqueue_run(db_session, run)
    old_timestamp = utc_now() - timedelta(seconds=120)
    run.queued_at = old_timestamp
    run.heartbeat_at = old_timestamp
    db_session.commit()

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    run_queue = body["checks"]["run_queue"]
    assert body["overall_status"] == "warning"
    assert run_queue["status"] == "warning"
    assert run_queue["queued_count"] == 1
    assert run_queue["oldest_queued_age_seconds"] >= 60


def test_readiness_reports_fresh_running_run_ready(
    client,
    monkeypatch,
    tmp_path,
    db_session,
    create_user,
):
    _set_readiness_settings(monkeypatch, artifacts_dir=tmp_path / "artifacts")
    user = create_user(email="queue-running@example.com")
    run = _create_health_run(db_session, user_id=user.id)
    now = utc_now()
    run.status = RunStatus.RUNNING
    run.started_at = now
    run.heartbeat_at = now
    run.leased_until = now + timedelta(seconds=300)
    db_session.commit()

    response = client.get("/health/readiness")

    assert response.status_code == 200
    run_queue = response.json()["checks"]["run_queue"]
    assert run_queue["status"] == "ready"
    assert run_queue["running_count"] == 1
    assert run_queue["stale_running_count"] == 0
    assert run_queue["oldest_running_heartbeat_age_seconds"] is not None


def test_readiness_reports_stale_running_run_not_ready(
    client,
    monkeypatch,
    tmp_path,
    db_session,
    create_user,
):
    _set_readiness_settings(
        monkeypatch,
        artifacts_dir=tmp_path / "artifacts",
        running_stale_seconds=300,
    )
    user = create_user(email="queue-stale@example.com")
    run = _create_health_run(db_session, user_id=user.id)
    stale_timestamp = utc_now() - timedelta(seconds=600)
    run.status = RunStatus.RUNNING
    run.started_at = stale_timestamp
    run.heartbeat_at = stale_timestamp
    run.leased_until = utc_now() - timedelta(seconds=1)
    db_session.commit()

    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    run_queue = body["checks"]["run_queue"]
    assert body["overall_status"] == "not_ready"
    assert run_queue["status"] == "not_ready"
    assert run_queue["running_count"] == 1
    assert run_queue["stale_running_count"] == 1
    assert run_queue["oldest_running_heartbeat_age_seconds"] >= 300


def test_readiness_queue_check_does_not_expose_run_or_user_details(
    client,
    monkeypatch,
    tmp_path,
    db_session,
    create_user,
):
    _set_readiness_settings(monkeypatch, artifacts_dir=tmp_path / "artifacts")
    user = create_user(email="private-queue-user@example.com")
    run = _create_health_run(
        db_session,
        user_id=user.id,
        payload={
            "strategy_name": "Private Momentum Strategy",
            "private_note": "never expose this payload",
        },
    )
    enqueue_run(db_session, run)

    response = client.get("/health/readiness")

    assert response.status_code == 200
    payload = response.text
    assert str(run.id) not in payload
    assert str(user.id) not in payload
    assert "private-queue-user@example.com" not in payload
    assert "Private Momentum Strategy" not in payload
    assert "never expose this payload" not in payload


def _create_health_run(db_session, *, user_id, payload: dict | None = None):
    return create_run(
        db_session,
        user_id=user_id,
        strategy_id=None,
        strategy_version_id=None,
        run_type=RunType.SIMULATION,
        executor_type=ExecutorType.SIMULATION_EXECUTOR,
        payload=payload or {"source": "health-readiness-test"},
    )
