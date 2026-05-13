# Beta Operator Runbook

Use this runbook when switching between normal local development, packaged Docker Compose smoke, and Auth0 beta QA. The main rule is to let exactly one stack own each shared port at a time.

## Mode A: Local Dev

Use local dev mode for normal feature work and real local configuration, including your real local `.env` data paths and local or S3 artifact settings.

For a quick automated product-loop check that does not start services or use external providers, run:

```bash
bash scripts/beta_smoke_core_loop.sh
```

Use this focused smoke while iterating on Builder, Gallery, run execution, artifacts, dashboards, rotation review, or compare. Use `bash scripts/beta_release_gate.sh` for the full local/code release gate before tester handoff.

### Ownership

- Postgres: local Postgres container.
- API: local `uvicorn`.
- Worker: local worker process.
- Frontend: local Vite dev server through `npm run dev`.

### Environment

Backend `.env`:

```bash
ENV=local
AUTH_MODE=dev
```

Frontend:

- `frontend/.env.local` is absent, or
- `frontend/.env.local` contains:

```bash
VITE_AUTH_PROVIDER=dev
```

### Start

Start the local Postgres container first, then run the API, worker, and frontend in separate terminals:

```bash
uvicorn market_simulator.api.main:app --reload
```

```bash
python -m market_simulator.platform.worker --recover-stale
```

```bash
cd frontend
npm run dev
```

Confirm the app at:

- Frontend: `http://localhost:5173`
- API: `http://127.0.0.1:8000`

## Mode B: Compose Smoke

Use compose smoke mode to verify the packaged beta-local Docker stack starts cleanly. This mode is for packaging smoke only, not real backtest QA.

### Ownership

Docker Compose owns Postgres, API, worker, and frontend. Do not run local `uvicorn`, the local worker, or `npm run dev` at the same time.

### Environment

`docker-compose.beta-local.yml` uses placeholder data paths so the stack can boot without private datasets. Placeholder market-data paths may produce readiness warnings. That is expected for packaging smoke and is not a substitute for QA against real curated market data.

This mode does not load `.env.beta.example` or `frontend/.env.beta.example`.

### Start

Stop any existing beta-local compose stack, then run the helper:

```bash
docker compose -f docker-compose.beta-local.yml down
bash scripts/smoke_compose_local.sh
```

When finished, stop compose:

```bash
docker compose -f docker-compose.beta-local.yml down
```

If local `uvicorn`, local worker, or `npm run dev` were running before the smoke test, restart them only after compose is down.

## Mode C: Auth0 Beta QA

Use Auth0 beta QA mode for browser and API testing of the beta auth path while still running services locally. This mode is meant to exercise OIDC login/logout, bearer-token API calls, external identity mapping, and the `BETA_TESTER` plan with real local or S3-backed data paths.

### Ownership

- Postgres: local Postgres container.
- API: local `uvicorn`.
- Worker: local worker process.
- Frontend: local Vite dev server through `npm run dev`.

Do not run the compose stack at the same time.

### Backend Environment

Backend `.env`:

```bash
ENV=beta
AUTH_MODE=oidc
OIDC_PROVIDER_NAME=auth0
OIDC_JWKS_URL=https://your-tenant.region.auth0.com/.well-known/jwks.json
OIDC_ISSUER=https://your-tenant.region.auth0.com/
OIDC_AUDIENCE=your-api-audience
```

For a deployed or local Auth0 beta QA env file, validate the shape before starting services:

```bash
python scripts/beta_preflight.py \
  --backend-env .env.beta \
  --frontend-env frontend/.env.beta \
  --target-env beta
```

Auth0 values:

- Domain: the Auth0 tenant domain, for example `your-tenant.region.auth0.com`.
- Client ID: the Auth0 SPA application client ID used by the frontend.
- Audience: the Auth0 API identifier expected in access tokens and configured as `OIDC_AUDIENCE`.

### Frontend Environment

`frontend/.env.local`:

```bash
VITE_AUTH_PROVIDER=auth0
VITE_AUTH0_DOMAIN=your-tenant.region.auth0.com
VITE_AUTH0_CLIENT_ID=your-spa-client-id
VITE_AUTH0_AUDIENCE=your-api-audience
# Optional when the callback differs from window.location.origin:
VITE_AUTH0_REDIRECT_URI=http://localhost:5173
```

### Provision A Beta Tester

Provision invited testers on the database-backed `BETA_TESTER` plan. Use the durable Auth0 subject when known:

```bash
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER \
  --external-provider auth0 \
  --external-subject "auth0-or-social-provider|subject"
```

If the Auth0 subject is not known yet, provision by email only when `OIDC_ALLOW_EMAIL_LINKING=true` is intentionally enabled for beta bootstrap:

```bash
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER
```

### Start

Run the API, worker, and frontend in separate terminals:

```bash
uvicorn market_simulator.api.main:app --reload
```

```bash
python -m market_simulator.platform.worker --recover-stale
```

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`, sign in with Auth0, confirm user entitlements show the `BETA_TESTER` plan, and verify sign-out returns the frontend to the auth-required state.

Before tester handoff, confirm `/health/readiness` reports `checks.run_queue.status` as `ready` or `warning` only because of old queued work, and confirm the worker terminal is still running. API alone is not enough for queued simulations.

### Restore Local Dev Mode

After Auth0 QA:

1. Stop local `uvicorn`, worker, and `npm run dev`.
2. Change backend `.env` back to:

```bash
ENV=local
AUTH_MODE=dev
```

3. Remove `frontend/.env.local` or set:

```bash
VITE_AUTH_PROVIDER=dev
```

4. Restart local dev mode services.

## Port Ownership

Only one process should own each shared port:

- `localhost:8000`: either compose API or local `uvicorn`, not both.
- `localhost:5173`: either compose frontend or local `npm run dev`, not both.
- `localhost:5432`: either compose Postgres or local Postgres, not both.

When behavior looks strange, first check whether both stacks are running. A common failure pattern is testing the compose frontend while local `uvicorn` is answering API requests, or testing the local frontend while compose owns the API.

## Quick Diagnostics

List running containers:

```bash
docker ps
```

Check port owners:

```bash
lsof -i :8000
lsof -i :5173
lsof -i :5432
```

Check API health:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/health/readiness
```

If compose owns the API, the same health URLs should still work through the compose-published API port.

## Run Queue Operations

Use the queue status helper when runs appear stuck, queue depth grows, or the worker terminal is quiet:

```bash
python scripts/run_queue_status.py
python scripts/run_queue_status.py --json
```

The helper prints aggregate-only diagnostics: pending, queued, running, stale running, recent failed counts, oldest pending/queued/running heartbeat ages, and suspicious old active work. It does not print run payloads, user identifiers, secrets, or stack traces.

Readiness exposes the same safe aggregate shape under `checks.run_queue`:

```bash
curl -fsS http://127.0.0.1:8000/health/readiness | jq '.checks.run_queue'
```

Interpretation:

- `status=ready`: no stale running work and no old queued work beyond `QUEUE_OLDEST_WARNING_SECONDS`.
- `status=warning`: queued work is old enough that the worker may not be claiming jobs. Confirm the worker process is running.
- `status=not_ready`: at least one running run is stale according to `RUNNING_STALE_SECONDS` or an expired worker lease.
- `failed_recent_count>0`: inspect failed run detail in the app/API and the worker logs for the full operator error context.
- `suspicious_old_pending_count>0`: check API enqueue logs; these runs were created but did not move into the queue promptly.

Recover stale running runs with the worker recovery path:

```bash
python -m market_simulator.platform.worker --recover-stale
```

Local dev admins can also use the local-only admin endpoint:

```bash
curl -X POST http://127.0.0.1:8000/runs/admin/recover-stale
```

Recovery is intentionally narrow: it requeues stale running runs that still have attempts remaining, marks them failed when max attempts are exhausted, leaves succeeded runs untouched, and does not delete or rewrite artifacts.

If artifacts are missing, first check the run detail response for `artifact_storage_type` and `artifact_root_uri`. Local artifact errors usually mean a container, temp directory, or local workspace was replaced; rerun the simulation if the source strategy is still valid. For beta/prod, prefer S3 artifact storage and verify `checks.artifact_storage` is ready before tester handoff.

If the worker is down, restart the worker command for the current mode, then re-check:

```bash
python -m market_simulator.platform.worker --recover-stale
python scripts/run_queue_status.py
```

## Environment Safety Checklist

- Never commit backend `.env`.
- Never commit `frontend/.env.local`.
- Never paste Auth0 client secrets, database credentials, private S3 bucket credentials, or local dataset paths into committed docs.
- Before committing, confirm no env files are tracked:

```bash
git ls-files | grep -E '(^|/)\.env($|\.local|\.production|\.development)' || true
```

Only `.env.example`-style templates should be committed.
