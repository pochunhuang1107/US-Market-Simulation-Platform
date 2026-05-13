# Beta Release Checklist

Use this before handing a beta build to testers. The first gate focuses on local/code release readiness. Hosted Vercel + Render + Postgres + S3 + Auth0 deployment steps are tracked separately below and expanded in [Hosted Beta Deployment](HOSTED_BETA_DEPLOYMENT.md).

## 0. Local Release Gate

- [ ] Run the safe local release gate from the repo root:

```bash
bash scripts/beta_release_gate.sh
```

This command runs backend tests, the frontend production build, beta env template preflight, `docker-compose.beta-local.yml` config validation, tracked env-file safety checks, and the landing/workspace route split check. It does not require AWS/Auth0 secrets, print env values, create cloud resources, or start the compose stack.

For a faster product-loop confidence check during feature work, run the focused beta smoke suite:

```bash
bash scripts/beta_smoke_core_loop.sh
```

The smoke suite uses synthetic local data to cover Builder, Gallery, rotation run review, run detail/chart/dashboard APIs, and compare. It is not a replacement for `scripts/beta_release_gate.sh`, which remains the full local release gate before tester handoff.

- [ ] Review [Ownership And Authorization Checklist](OWNERSHIP_AUTHORIZATION.md) when adding or changing any user-scoped API route.
- [ ] Review [Reference-Series And Regime Filters](REFERENCE_SERIES_REGIME_FILTERS.md) when changing reference-series data, regime rules, Gallery templates, or builder parsing.

## 1. Environment Shape

- [ ] Backend env is based on `.env.beta.example`, with real values supplied only in the deployment environment or private secret store.
- [ ] Frontend build env is based on `frontend/.env.beta.example`.
- [ ] Local dev still uses `.env.example` and `frontend/.env.example`; compose smoke still uses `docker-compose.beta-local.yml`.
- [ ] No real `.env` or `frontend/.env.local` files are tracked. The release gate checks this automatically:

```bash
git ls-files | grep -E '(^|/)\.env($|\.)' | grep -Ev '(^|/)\.env(\.beta)?\.example$' || true
```

- [ ] Safe preflight passes without printing secrets. For committed templates, the release gate runs this automatically:

```bash
python scripts/beta_preflight.py \
  --backend-env .env.beta.example \
  --frontend-env frontend/.env.beta.example \
  --target-env beta
```

For a private beta deployment environment, run the same preflight against private env files or the current process environment outside git.

## 2. Required Backend Vars

- [ ] `DATABASE_URL` points to durable Postgres.
- [ ] `ENV=beta`.
- [ ] `AUTH_MODE=oidc`.
- [ ] `OIDC_JWKS_URL`, `OIDC_ISSUER`, and `OIDC_AUDIENCE` match the Auth0/OIDC API configuration.
- [ ] `OIDC_PROVIDER_NAME` is set to `auth0` for Auth0 beta identity links, or the chosen provider name.
- [ ] Curated data paths are configured: `MARKET_DATA_PATH`, `ETF_METADATA_S3_URI`, `REFERENCE_SERIES_DATA_PATH`, `REFERENCE_SERIES_METADATA_S3_URI`.
- [ ] `ARTIFACT_STORAGE_BACKEND=S3`, `ARTIFACT_S3_BUCKET`, `ARTIFACT_S3_PREFIX`, and `ARTIFACT_S3_REGION` are configured.
- [ ] `ENABLE_DEV_ADMIN_OVERRIDE=false`.

## 3. Required Frontend Vars

- [ ] `VITE_AUTH_PROVIDER=auth0`.
- [ ] `VITE_AUTH0_DOMAIN` is the Auth0 tenant domain.
- [ ] `VITE_AUTH0_CLIENT_ID` is the Auth0 SPA application client ID.
- [ ] `VITE_AUTH0_AUDIENCE` matches backend `OIDC_AUDIENCE`.
- [ ] `VITE_AUTH0_REDIRECT_URI` matches the deployed frontend callback when it differs from `window.location.origin`.

## 4. Migrations And Processes

- [ ] Run database migrations before serving traffic:

```bash
alembic upgrade head
```

- [ ] Start the API process.
- [ ] Start the worker process; API alone will not execute queued simulations:

```bash
python -m market_simulator.platform.worker --recover-stale
```

## 5. Health And Queue

- [ ] API liveness is healthy:

```bash
curl -fsS "$API_BASE/health"
```

- [ ] Readiness is `ready` before tester access:

```bash
curl -fsS "$API_BASE/health/readiness" | jq .
```

- [ ] Worker/queue readiness is not blocked:

```bash
curl -fsS "$API_BASE/health/readiness" | jq '.checks.run_queue'
```

- [ ] `checks.artifact_storage.backend` is `S3` for beta/prod. Treat local artifacts in beta/prod as a release blocker unless the test is explicitly local-only.

## 6. Beta Users

- [ ] Provision each invited tester on the `BETA_TESTER` plan:

```bash
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER \
  --external-provider auth0 \
  --external-subject "auth0-or-social-provider|subject"
```

- [ ] If the external subject is not known yet, only provision by email when `OIDC_ALLOW_EMAIL_LINKING=true` is intentionally enabled for first-login bootstrap.

## 7. Product Smoke

- [ ] Run the automated focused product-loop smoke when changing Builder, Gallery, run execution, artifacts, dashboards, rotation review, or compare:

```bash
bash scripts/beta_smoke_core_loop.sh
```

- [ ] Open Gallery and start from a curated strategy.
- [ ] Open Builder and create a simple draft strategy.
- [ ] Queue a run and confirm the worker advances it to completed.
- [ ] Open Run Detail and confirm metrics/charts render.
- [ ] Compare one completed run against another completed run or a selected sweep variant.
- [ ] Run the fuller manual pass in [Beta Smoke Checklist](BETA_SMOKE_CHECKLIST.md) when changing auth, artifacts, data paths, or run execution.

## 8. Hosted Beta Dry Run

- [ ] Complete the operator dry-run checklist in [Hosted Beta Deployment](HOSTED_BETA_DEPLOYMENT.md) before applying the hosted beta stack or handing it to testers.
- [ ] Confirm `render.yaml` and `vercel.json` have no real secrets and any `sync: false` values are supplied privately in the hosting provider.
- [ ] Confirm the hosted workflow covers backend, worker, frontend, database/user provisioning, smoke tests, queue recovery, S3 artifact verification, and rollback.
