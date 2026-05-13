# Hosted Beta Deployment

This is the operator dry-run checklist for the current hosted beta stack:

- Frontend: Vercel static Vite build.
- Backend API: Render Docker web service.
- Worker: Render Docker background worker.
- Database: managed Postgres.
- Artifacts and curated data: S3.
- Auth: Auth0 OIDC.

This document is for deployment rehearsal and operator readiness only. Do not deploy from it automatically, do not commit real secrets, and do not change runtime architecture to satisfy a dry run.

## Safety Rules

- Do not commit `.env`, `.env.beta`, `frontend/.env.local`, real bucket names, database URLs, IAM keys, Auth0 secrets, tenant-specific private values, or provider keys.
- Keep `render.yaml`, `vercel.json`, `.env.beta.example`, and `frontend/.env.beta.example` placeholder-only.
- Run hosted commands in a shell/job that has the hosted `DATABASE_URL` and private env injected by the hosting provider, not in committed files.
- Hosted services are never required in CI. Local release gates must stay secret-free.

## Existing Hosting Config

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

The API service has `preDeployCommand: alembic upgrade head`. For manual operation, non-blueprint databases, or a failed/uncertain predeploy run, execute the same command in a hosted shell/job with the deployed `DATABASE_URL`.

`vercel.json` keeps the repository root as the Vercel project root and configures:

- Install command: `npm --prefix frontend ci`
- Build command: `npm --prefix frontend run build`
- Output directory: `frontend/dist`
- SPA fallback to `index.html`
- `/api/*` rewrite to the Render API, stripping the `/api` prefix to match backend routes.

If Render assigns a different API hostname, update only the `/api/:path*` rewrite destination. The frontend currently calls relative `/api/...` routes; the hosted API base URL is the Vercel rewrite destination, not a browser-exposed secret.

## Environment Checklist

### Required Backend Env

Set these on both the Render API and worker unless noted:

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
- `OIDC_ALLOW_EMAIL_LINKING=true` only while email bootstrap linking is intentionally allowed.
- `ARTIFACT_STORAGE_BACKEND=S3`
- `ARTIFACT_S3_BUCKET`
- `ARTIFACT_S3_PREFIX`
- `ARTIFACT_S3_REGION`
- `ARTIFACT_PRESIGN_TTL_SECONDS=3600`
- `MARKET_DATA_PATH`
- `ETF_METADATA_S3_URI`
- `REFERENCE_SERIES_DATA_PATH`
- `REFERENCE_SERIES_METADATA_S3_URI`
- `S3_REGION`
- `ENABLE_DEV_ADMIN_OVERRIDE=false`
- `QUEUE_OLDEST_WARNING_SECONDS=600`
- `RUNNING_STALE_SECONDS=300`

Provide AWS credentials through Render secrets or another private credential mechanism supported by the runtime. If using static IAM credentials on Render, set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; set `AWS_SESSION_TOKEN` only for temporary credentials.

### Required Frontend Env

Set these Vercel environment variables for the beta project:

- `VITE_AUTH_PROVIDER=auth0`
- `VITE_AUTH0_DOMAIN`
- `VITE_AUTH0_CLIENT_ID`
- `VITE_AUTH0_AUDIENCE`
- `VITE_AUTH0_REDIRECT_URI`
- `VITE_AUTH0_CACHE_LOCATION=memory`
- `VITE_AUTH0_USE_REFRESH_TOKENS=false`

`VITE_AUTH0_AUDIENCE` must match backend `OIDC_AUDIENCE`. `VITE_AUTH0_REDIRECT_URI` should be the hosted frontend origin unless a specific callback URL is required. Do not put backend-only secrets in Vercel; all `VITE_*` values are exposed to the browser bundle.

### Optional OpenAI Env

The beta-safe default is deterministic builder translation:

```bash
STRATEGY_BUILDER_PROVIDER=deterministic
```

Hybrid mode is acceptable when product-like fallback behavior is desired and usage limits are configured:

```bash
STRATEGY_BUILDER_PROVIDER=hybrid
OPENAI_API_KEY=<set privately in the host only>
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=20
OPENAI_MAX_RETRIES=1
OPENAI_FALLBACK_DAILY_LIMIT_PER_USER=25
OPENAI_FALLBACK_DAILY_LIMIT_BY_PLAN=FREE:0,BETA_TESTER:100,PRO:100,RESEARCH:100,DEV_ADMIN:unlimited
OPENAI_FALLBACK_MAX_PROMPT_CHARS=4000
```

Use `STRATEGY_BUILDER_PROVIDER=openai` only for direct adapter testing. Do not commit `OPENAI_API_KEY` or provider secrets.

### Optional Model Signal Env

Model-signal loading is optional and disabled when the path is empty:

```bash
MODEL_SIGNAL_DATA_PATH=
```

Set `MODEL_SIGNAL_DATA_PATH` only when hosted beta should run model-signal strategies against validated runtime artifacts, for example a private curated S3 path matching [Model Signal Ingestion Contract](MODEL_SIGNAL_INGESTION_CONTRACT.md). This platform does not train models or run live inference.

### Local-Only Dev Override Env

These are local development conveniences and should not be enabled for hosted beta:

- `ENV=local`
- `AUTH_MODE=dev`
- `DEV_DEFAULT_USER_ID`
- `DEV_ADMIN_USER_IDS`
- `ENABLE_DEV_ADMIN_OVERRIDE=true`
- `ARTIFACT_STORAGE_BACKEND=LOCAL`
- `ARTIFACTS_DIR`
- `VITE_AUTH_PROVIDER=dev`
- Browser local storage manual access-token helpers.

## Auth0 Checklist

In the Auth0 SPA application, configure:

- Allowed Callback URLs: the hosted Vercel frontend URL and any custom frontend domain.
- Allowed Logout URLs: the hosted Vercel frontend URL and any custom frontend domain.
- Allowed Web Origins: the hosted Vercel frontend origin.
- API audience: the same value used for backend `OIDC_AUDIENCE` and frontend `VITE_AUTH0_AUDIENCE`.

Google login is fine for beta: Auth0 still issues the application access token, and the backend validates the Auth0-issued JWT against the configured issuer, JWKS, and audience.

## S3 Permissions

The API and worker need enough AWS access to:

- Read curated ETF parquet data under `MARKET_DATA_PATH`.
- Read ETF metadata at `ETF_METADATA_S3_URI`.
- Read reference-series data under `REFERENCE_SERIES_DATA_PATH`.
- Read reference-series metadata at `REFERENCE_SERIES_METADATA_S3_URI`.
- Read model-signal artifacts under `MODEL_SIGNAL_DATA_PATH` when configured.
- Write and read simulation artifacts under `s3://$ARTIFACT_S3_BUCKET/$ARTIFACT_S3_PREFIX/`.
- Presign artifact reads if the artifact store uses presigned URLs.

Keep permissions scoped to curated data paths and the artifact prefix. Do not commit IAM users, keys, account IDs, or account-specific policies.

## Hosted Beta Dry-Run Checklist

Use this checklist before the first hosted beta deployment and before any later beta environment change.

### 1. Pre-Deploy

- [ ] Confirm the branch is based on a clean, reviewed `main` and the worktree has no surprise changes:

```bash
git status --short --branch
git fetch origin
git log --oneline --decorate --max-count=5 origin/main..HEAD
```

- [ ] Run the local release gate from the repo root:

```bash
bash scripts/beta_release_gate.sh
```

- [ ] Run static beta preflight against placeholder templates:

```bash
python scripts/beta_preflight.py \
  --backend-env .env.beta.example \
  --frontend-env frontend/.env.beta.example \
  --target-env beta
```

- [ ] Run static beta preflight against private hosted env values outside git. Use `--current-env` only from a dry-run shell where both backend and frontend vars are exported:

```bash
python scripts/beta_preflight.py --current-env --target-env beta
```

- [ ] Confirm migrations are current in the target database plan and that the deploy path will run:

```bash
alembic upgrade head
```

- [ ] Confirm env templates were reviewed and no real env files are tracked:

```bash
git ls-files | grep -E '(^|/)\.env($|\.)' | grep -Ev '(^|/)\.env(\.beta)?\.example$' || true
```

- [ ] Confirm generated reports, local artifacts, build outputs, and coverage output are not tracked:

```bash
git ls-files | grep -E '(^|/)(artifacts|reports|data/local_artifacts|data/discovery_reports|frontend/dist|dist|coverage|htmlcov|playwright-report)(/|$)' || true
```

### 2. Backend Hosting

- [ ] Render API service uses `Dockerfile.backend`.
- [ ] API command is exactly:

```bash
uvicorn market_simulator.api.main:app --host 0.0.0.0 --port 8000
```

- [ ] `DATABASE_URL` points to the managed hosted Postgres database.
- [ ] Required backend env is present on the API service.
- [ ] Auth0 OIDC vars match the Auth0 tenant and API audience.
- [ ] S3 artifact vars point to the beta artifact bucket/prefix.
- [ ] Market data and reference-series path vars point to curated app-ready datasets.
- [ ] `MODEL_SIGNAL_DATA_PATH` is empty unless validated model-signal artifacts are intentionally part of the dry run.
- [ ] OpenAI provider vars are disabled by default or configured privately with limits for hybrid fallback.
- [ ] `/health` and `/health/readiness` are reachable after the API starts:

```bash
API_BASE=https://your-beta-api.example.com
curl -fsS "$API_BASE/health" | jq .
curl -fsS "$API_BASE/health/readiness" | jq .
```

### 3. Worker Hosting

- [ ] Render worker service uses the same backend image as the API.
- [ ] Worker env matches backend runtime needs: `DATABASE_URL`, auth env, S3 artifact env, curated data env, optional model-signal env, queue thresholds, and private AWS credentials.
- [ ] Worker command is exactly:

```bash
python -m market_simulator.platform.worker --recover-stale
```

- [ ] Queue status can be checked from a hosted shell/job with the worker env:

```bash
python scripts/run_queue_status.py
python scripts/run_queue_status.py --json
```

- [ ] Readiness exposes queue health and is not blocked:

```bash
curl -fsS "$API_BASE/health/readiness" | jq '.checks.run_queue'
```

- [ ] Stale run recovery path is known:

```bash
python -m market_simulator.platform.worker --recover-stale
```

### 4. Frontend Hosting

- [ ] Vercel project uses `vercel.json` from the repo root.
- [ ] Install command is `npm --prefix frontend ci`.
- [ ] Build command is `npm --prefix frontend run build`.
- [ ] Output directory is `frontend/dist`.
- [ ] `/api/:path*` rewrite points at the actual Render API hostname and strips the `/api` prefix.
- [ ] Required frontend env is present in Vercel.
- [ ] Auth0 Allowed Callback URLs, Logout URLs, and Web Origins include the hosted Vercel URL and any custom domain.
- [ ] Route split is preserved: `/` is the landing page, `/workspace` is the app, and `/chat` redirects to `/workspace`.

### 5. Database And Users

- [ ] Run migrations in the hosted database context when the API predeploy command did not already do so:

```bash
alembic upgrade head
```

- [ ] Seed plans in the hosted database context:

```bash
python scripts/seed_plans.py
```

- [ ] Provision each invited beta tester on `BETA_TESTER` by Auth0 subject when available:

```bash
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER \
  --external-provider auth0 \
  --external-subject "auth0-or-social-provider|subject"
```

- [ ] If the Auth0 subject is not known before first login, provision by email only and keep `OIDC_ALLOW_EMAIL_LINKING=true` intentionally enabled for bootstrap:

```bash
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER
```

- [ ] Verify the tester can load entitlements through browser login:

```bash
curl -fsS "$API_BASE/me/entitlements" -H "Authorization: Bearer $ACCESS_TOKEN" | jq '{plan, features, limits, usage}'
```

### 6. Hosted Smoke Tests

- [ ] API liveness and readiness pass:

```bash
curl -fsS "$API_BASE/health" | jq .
curl -fsS "$API_BASE/health/readiness" | jq .
```

- [ ] `/health/readiness` reports `ENV=beta`, OIDC auth, S3 artifact storage, curated S3 market/reference data paths, database readiness, and queue readiness.
- [ ] Sign in through Auth0 in the hosted browser flow.
- [ ] Open `/workspace` and confirm `/me/entitlements` loads for the signed-in `BETA_TESTER`.
- [ ] Create a simple RSI builder run, for example `Create a QQQ mean reversion strategy with RSI below 35 and exit when RSI is above 65.`
- [ ] Run a Gallery rotation template.
- [ ] Confirm each run queues, the worker completes it, and run detail loads.
- [ ] Compare two completed run results.
- [ ] Check worker queue status:

```bash
python scripts/run_queue_status.py
curl -fsS "$API_BASE/health/readiness" | jq '.checks.run_queue'
```

- [ ] Verify S3 artifacts exist under the configured artifact prefix for completed runs. Do not paste bucket names or object keys into committed docs.

### 7. Rollback And Recovery

- [ ] Frontend rollback: use Vercel deployment rollback to return traffic to the previous known-good frontend deployment.
- [ ] Backend rollback: redeploy the previous known-good Render API image/commit and re-check `/health/readiness`.
- [ ] Worker stop/restart: stop the Render worker to halt new run execution, then restart the previous known-good worker image/commit when ready.
- [ ] Failed migration handling: keep the old API serving if predeploy migration fails. For partially applied or destructive migrations, pause deploys and restore from the managed Postgres backup/snapshot according to the database provider runbook before retrying.
- [ ] Stale run recovery: after worker restart or rollback, run:

```bash
python -m market_simulator.platform.worker --recover-stale
python scripts/run_queue_status.py
```

- [ ] Missing artifacts: inspect run detail for `artifact_storage_type` and `artifact_root_uri`; for hosted beta, fix S3 env/permissions and rerun affected simulations rather than editing artifact records by hand.

## Known Hosted Beta Limitations

- OpenAI fallback can be slow and may add cost. `STRATEGY_BUILDER_PROVIDER=hybrid` reduces usage by keeping common prompts on the deterministic path.
- Model-signal support is backend/runtime foundation, not a UI-first workflow. It requires validated precomputed artifacts and does not train models or run live inference.
- This platform is for research and simulation. It is not live trading infrastructure and does not guarantee signals, returns, or investment outcomes.
- Free/Pro plan and payment integration may still be manual during beta; invited testers should be provisioned explicitly on `BETA_TESTER`.

## Final Verification

For docs-only changes, no new tests are required. Before handing this branch off, still run the existing acceptance checks:

```bash
pytest
npm --prefix frontend run build
```
