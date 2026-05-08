# Hosted Beta Deployment

This is the practical hosted beta path for the current stack:

- Frontend: Vercel static Vite build.
- Backend API: Render Docker web service.
- Worker: Render Docker background worker.
- Database: managed Postgres.
- Artifacts and curated data: S3.
- Auth: Auth0 OIDC.

Do not commit `.env`, `.env.beta`, `frontend/.env.local`, real bucket names, database URLs, IAM keys, Auth0 secrets, or tenant-specific private values.

## Render

`render.yaml` defines a safe blueprint for:

- `us-market-simulation-api-beta`: Docker web service using `Dockerfile.backend`.
- `us-market-simulation-worker-beta`: Docker background worker using the same image.
- `us-market-simulation-postgres-beta`: managed Render Postgres.

The API command is:

```bash
uvicorn market_simulator.api.main:app --host 0.0.0.0 --port 8000
```

The worker command is:

```bash
python -m market_simulator.platform.worker --recover-stale
```

The blueprint leaves deployment-specific values as `sync: false`. Fill them in Render with private values. `DATABASE_URL` can reference a managed Postgres database or be supplied manually from another managed Postgres provider. If using Render Postgres, verify the SQLAlchemy URL works with the installed driver; use the same value for the API and worker.

Run migrations before traffic reaches the API. The blueprint sets `preDeployCommand: alembic upgrade head` on the API service. For manual operation or a non-blueprint database, run the same command in a Render shell/job with the deployed `DATABASE_URL`.

## Vercel

`vercel.json` keeps the repository root as the Vercel project root and configures:

- Install command: `npm --prefix frontend ci`
- Build command: `npm --prefix frontend run build`
- Output directory: `frontend/dist`
- SPA fallback to `index.html`
- `/api/*` rewrite to the Render API, stripping the `/api` prefix to match the existing backend routes.

If Render assigns a different API hostname, update only the `/api/:path*` rewrite destination. Do not put Auth0 secrets or backend-only secrets in Vercel. Vite exposes `VITE_*` values in the browser bundle.

## Backend Environment

Set these on both Render API and worker services unless noted:

- `DATABASE_URL`: managed Postgres URL used by both processes.
- `ENV=beta`
- `AUTH_MODE=oidc`
- `OIDC_PROVIDER_NAME=auth0`
- `OIDC_JWKS_URL`: Auth0 JWKS endpoint.
- `OIDC_ISSUER`: Auth0 issuer, including the trailing slash when Auth0 uses one.
- `OIDC_AUDIENCE`: Auth0 API audience.
- `OIDC_EMAIL_CLAIM=email`
- `OIDC_SUBJECT_CLAIM=sub`
- `OIDC_DISPLAY_NAME_CLAIM=name`
- `OIDC_ALLOW_EMAIL_LINKING=true` for first-login bootstrap when users are provisioned by email only.
- `ARTIFACT_STORAGE_BACKEND=S3`
- `ARTIFACT_S3_BUCKET`
- `ARTIFACT_S3_PREFIX`
- `ARTIFACT_S3_REGION`
- `MARKET_DATA_PATH`
- `ETF_METADATA_S3_URI`
- `REFERENCE_SERIES_DATA_PATH`
- `REFERENCE_SERIES_METADATA_S3_URI`
- `S3_REGION`
- `ENABLE_DEV_ADMIN_OVERRIDE=false`

Provide AWS credentials through Render secrets or another private credential mechanism supported by the runtime. Do not commit them. If using static IAM credentials on Render, set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; set `AWS_SESSION_TOKEN` only for temporary credentials.

## Frontend Environment

Set these Vercel environment variables for the beta project:

- `VITE_AUTH_PROVIDER=auth0`
- `VITE_AUTH0_DOMAIN`
- `VITE_AUTH0_CLIENT_ID`
- `VITE_AUTH0_AUDIENCE`
- `VITE_AUTH0_REDIRECT_URI`
- `VITE_AUTH0_CACHE_LOCATION`
- `VITE_AUTH0_USE_REFRESH_TOKENS`

`VITE_AUTH0_AUDIENCE` must match backend `OIDC_AUDIENCE`. `VITE_AUTH0_REDIRECT_URI` should be the hosted frontend origin unless a specific callback URL is required.

## Auth0 Checklist

In the Auth0 SPA application, configure:

- Allowed Callback URLs: the hosted Vercel frontend URL, and any custom frontend domain.
- Allowed Logout URLs: the hosted Vercel frontend URL, and any custom frontend domain.
- Allowed Web Origins: the hosted Vercel frontend origin.
- API audience: the same value used for backend `OIDC_AUDIENCE` and frontend `VITE_AUTH0_AUDIENCE`.

Google login is fine for beta: Auth0 still issues the application access token, and the backend validates the Auth0-issued JWT against the configured issuer, JWKS, and audience.

## Database And Users

Use the deployed `DATABASE_URL` context for all hosted beta database operations:

```bash
alembic upgrade head
python scripts/seed_plans.py
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER \
  --external-provider auth0 \
  --external-subject "auth0-or-social-provider|subject"
```

If the Auth0 subject is not known before first login, provision by email only:

```bash
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER
```

With `OIDC_ALLOW_EMAIL_LINKING=true`, the first valid OIDC login for a provisioned email can create the durable provider+subject link. Turn it off after beta users are pre-linked by subject if you no longer need bootstrap linking.

## S3 Permissions

The API and worker need enough AWS access to:

- Read curated ETF parquet data under `MARKET_DATA_PATH`.
- Read ETF metadata at `ETF_METADATA_S3_URI`.
- Read reference-series data under `REFERENCE_SERIES_DATA_PATH`.
- Read reference-series metadata at `REFERENCE_SERIES_METADATA_S3_URI`.
- Write and read simulation artifacts under `s3://$ARTIFACT_S3_BUCKET/$ARTIFACT_S3_PREFIX/`.
- Presign artifact reads if the artifact store uses presigned URLs.

Keep permissions scoped to the curated data paths and artifact prefix. Do not commit IAM users, keys, account IDs, or account-specific policies.

## Hosted Release Checklist

1. Run the local gate from the repo root:

```bash
bash scripts/beta_release_gate.sh
```

2. Deploy the Render API and worker from `render.yaml`, filling all `sync: false` values privately.
3. Deploy the Vercel frontend with `vercel.json`, and confirm the `/api/*` rewrite points at the actual Render API hostname.
4. Run `alembic upgrade head` against hosted Postgres if it did not run as the API predeploy command.
5. Run `python scripts/seed_plans.py` if plans are missing.
6. Provision invited beta users by email, and by Auth0 subject when available.
7. Verify API health:

```bash
curl -fsS "$API_BASE/health"
curl -fsS "$API_BASE/health/readiness"
```

8. Confirm `/health/readiness` reports beta, OIDC, S3 artifact storage, curated S3 data paths, database readiness, and queue readiness.
9. Sign in through Auth0 from the hosted frontend, then sign out.
10. Run one real S3-backed simulation from the hosted frontend.
11. Confirm the worker completes the run.
12. Verify artifact files exist under the configured S3 artifact prefix.
13. Open the run detail page and confirm metrics/charts load from S3-backed artifacts.
