# Deployment Packaging

This branch adds packaging for beta-like smoke testing only. It does not choose a real deployment target, deploy to AWS, create infrastructure, or commit secrets.

## Process Model

The app is packaged as four runtime processes:

- API: FastAPI served by `uvicorn market_simulator.api.main:app` on port `8000`.
- Worker: the same backend image with the command overridden to `python -m market_simulator.platform.worker --recover-stale`.
- Frontend: Vite static build served by nginx on port `80`.
- Postgres: durable application database used by the API and worker.

The backend image is intentionally reusable for the API and worker. Runtime environment variables come from the deploy environment; the Dockerfiles do not bake `.env` files, access tokens, bucket names, or OIDC secrets into images.

CI validates that the backend image, frontend image, and beta-local compose configuration still build or parse successfully. That validation does not push images to a registry, deploy infrastructure, or require secrets or AWS credentials.

## Local Beta-Like Compose

Start the packaged local stack:

```bash
docker compose -f docker-compose.beta-local.yml up --build
```

The compose stack starts Postgres, runs Alembic migrations before the API starts, seeds local plans plus the default dev user, runs the worker from the backend image, and serves the frontend at `http://localhost:5173`. The frontend nginx config mirrors Vite dev behavior by accepting `/api/*` browser calls and proxying them to the backend with the `/api` prefix stripped.

`docker-compose.beta-local.yml` intentionally does not load private `.env` values. It is self-contained and uses local dev auth, the compose Postgres service, local artifact storage, and placeholder curated-data S3 paths such as `s3://your-market-data-bucket/curated/...`. This compose file is for packaging/process smoke only; readiness may report warnings for placeholder data paths.

The automatic seed step is only for local beta-like smoke with dev auth. It initializes the fixed local dev user so user-scoped routes such as `/me/entitlements` work on a fresh compose Postgres volume; it does not provision real beta testers. For real local market-data or S3 artifact testing, use the non-Docker local workflow with your private `.env`, or create a private compose override file that is not committed.

Stop the stack with:

```bash
docker compose -f docker-compose.beta-local.yml down
```

Use `--volumes` only when you intentionally want to delete the local compose Postgres and artifact volumes.

For a repeatable packaging smoke from a fresh local compose environment, run:

```bash
bash scripts/smoke_compose_local.sh
```

The helper starts `docker-compose.beta-local.yml` with `up --build -d`, waits for `/health` to return `{"status":"ok"}`, checks `/health/readiness`, and verifies `/me/entitlements` returns the seeded default dev user on the `FREE` plan. It leaves the stack running by default; pass `--down` to stop the stack after the smoke check without deleting volumes:

```bash
bash scripts/smoke_compose_local.sh --down
```

## Required Beta Environment

For beta, configure these values in the target runtime environment or secret manager:

- `DATABASE_URL`: durable Postgres URL.
- `ENV=beta`.
- `AUTH_MODE=oidc`.
- `OIDC_JWKS_URL`: JWKS endpoint for the OIDC provider.
- `OIDC_ISSUER`: expected token issuer, recommended.
- `OIDC_AUDIENCE`: expected API audience, recommended.
- `OIDC_EMAIL_CLAIM`: defaults to `email`.
- `OIDC_SUBJECT_CLAIM`: defaults to `sub`.
- `OIDC_DISPLAY_NAME_CLAIM`: defaults to `name`.
- `OIDC_PROVIDER_NAME`: defaults to `oidc`.
- `OIDC_ALLOW_EMAIL_LINKING`: defaults to `true` for beta email-to-subject bootstrap.
- `MARKET_DATA_PATH`: curated ETF parquet path.
- `ETF_METADATA_S3_URI`: curated ETF metadata parquet URI.
- `REFERENCE_SERIES_DATA_PATH`: curated reference-series path.
- `REFERENCE_SERIES_METADATA_S3_URI`: curated reference-series metadata URI.
- `SUPPORTED_DATA_START_DATE`: defaults to `2018-01-02`.
- `SUPPORTED_DATA_END_DATE`: optional; defaults to the current date.
- `SUPPORTED_ETF_SYMBOLS`: optional override for the supported ETF universe.
- `SUPPORTED_REFERENCE_SERIES_SYMBOLS`: optional override for supported reference series.
- `ARTIFACT_STORAGE_BACKEND`: `LOCAL` or `S3`.

See [Beta Environment](BETA_ENVIRONMENT.md) for the existing auth and beta configuration notes.

## Artifact Storage

`LOCAL` storage is suitable for local development and compose smoke:

```text
ARTIFACT_STORAGE_BACKEND=LOCAL
ARTIFACTS_DIR=/app/data/local_artifacts
```

For beta, use S3 when run outputs must survive container replacement and be shared across API and worker processes:

```text
ARTIFACT_STORAGE_BACKEND=S3
ARTIFACT_S3_BUCKET=your-artifact-bucket
ARTIFACT_S3_PREFIX=artifacts
ARTIFACT_S3_REGION=us-west-2
ARTIFACT_PRESIGN_TTL_SECONDS=3600
```

Committed examples must stay placeholder-only. Do not commit real bucket names, access keys, `.env` files, or provider secrets.

## Readiness Check

After the API starts, check:

```bash
curl -fsS http://127.0.0.1:8000/health/readiness
```

The endpoint returns `overall_status` plus checks for app environment, database connectivity, auth configuration, artifact storage, data paths, and supported symbols. Treat `overall_status=ready` as the beta target. A `warning` usually means placeholder data paths are still configured; `not_ready` needs investigation before testers begin.

## User Provisioning

OIDC beta users must exist in the app database before first login:

```bash
python scripts/provision_user.py --email user@example.com --display-name "User Name" --plan-code FREE --external-provider oidc --external-subject abc123
```

The command is idempotent. Use the same deployed `DATABASE_URL` context that the API uses. If the external subject is not known yet, provision by email only and keep `OIDC_ALLOW_EMAIL_LINKING=true` for the first login bootstrap.

Do not rely on the compose local seed for beta or production users. Protected beta/prod environments should provision users explicitly with `scripts/provision_user.py`.

## Smoke Checklist

Minimum local packaging smoke:

```bash
pytest
cd frontend
npm run build
cd ..
docker build -f Dockerfile.backend -t us-market-platform-api .
docker run --rm us-market-platform-api python -m market_simulator.platform.worker --help
docker build -f frontend/Dockerfile -t us-market-platform-frontend ./frontend
docker compose -f docker-compose.beta-local.yml up --build
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/health/readiness
bash scripts/smoke_compose_local.sh
```

For a product-loop pass, use [Beta Smoke Checklist](BETA_SMOKE_CHECKLIST.md).

## Existing Local Development

The non-Docker workflow remains supported:

```bash
uvicorn market_simulator.api.main:app --reload
python -m market_simulator.platform.worker --recover-stale
cd frontend
npm run dev
```

The Vite dev server continues to proxy `/api` to the local backend.
