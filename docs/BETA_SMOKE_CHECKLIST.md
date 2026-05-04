# Beta Smoke Checklist

Use this as a concise manual pass before handing a beta build to testers. Keep the pass focused on the existing product loop; do not use it to validate new product behavior.

## Local Setup

- [ ] Copy `.env.example` to `.env` and keep `ENV=local` with `AUTH_MODE=dev`.
- [ ] Confirm local Postgres is reachable through `DATABASE_URL`.
- [ ] Seed the local dev user if needed for the non-Docker workflow:

```bash
python scripts/seed_plans.py
python scripts/seed_user.py
```

- [ ] For `docker-compose.beta-local.yml` smoke, skip manual seed commands; compose runs migrations and local dev seeding during API startup.
- [ ] Optionally run the packaged compose helper to start the beta-local stack and verify `/health`, `/health/readiness`, and seeded local dev entitlements:

```bash
bash scripts/smoke_compose_local.sh
```

Stop the helper-started stack when finished:

```bash
docker compose -f docker-compose.beta-local.yml down
```

- [ ] Confirm curated ETF and reference-series paths are configured for the environment under test.
- [ ] Confirm artifact storage is local for local smoke (`ARTIFACT_STORAGE_BACKEND=LOCAL`) or S3 only for the protected beta environment.

## Start Services

- [ ] Start the backend:

```bash
uvicorn market_simulator.api.main:app --reload
```

- [ ] Start the run worker in a second terminal:

```bash
python -m market_simulator.platform.worker --recover-stale
```

- [ ] Start the frontend in a third terminal:

```bash
cd frontend
npm run dev
```

- [ ] Open the frontend at `http://localhost:5173`.

## API Smoke

Set local shell defaults:

```bash
API_BASE=http://127.0.0.1:8000
DEV_USER_ID=00000000-0000-0000-0000-000000000001
```

- [ ] Health returns `{"status":"ok"}`:

```bash
curl -fsS "$API_BASE/health" | jq .
```

- [ ] Readiness reports database/auth/artifact/data-path preflight status before deeper smoke:

```bash
curl -fsS "$API_BASE/health/readiness" | jq .
```

- [ ] Confirm queue/worker readiness is not blocked. `checks.run_queue.status` may be `ready` with zero jobs; `not_ready` means stale running work needs worker/recovery attention before product-loop QA:

```bash
curl -fsS "$API_BASE/health/readiness" | jq '.checks.run_queue'
```

- [ ] Confirm the worker process is running before product-loop QA so newly queued runs can be claimed and heartbeat during execution.

- [ ] Confirm `overall_status` is `ready` before beta testing, or review any `warning` / `not_ready` checks and fix the environment configuration. Placeholder market-data paths in beta-local compose may produce `warning`; do not proceed if `checks.run_queue.status` is `not_ready`.

- [ ] Local dev entitlements load for the seeded user:

```bash
curl -fsS \
  -H "X-User-Id: $DEV_USER_ID" \
  "$API_BASE/me/entitlements" | jq '{plan, features, limits, usage}'
```

- [ ] Strategy builder creates a VIX + RSI draft with `response_type` of `CREATE_DRAFT`:

```bash
curl -fsS \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $DEV_USER_ID" \
  -d '{"prompt":"Only trade QQQ when VIX is below 25 and RSI is below 35."}' \
  "$API_BASE/strategy-builder/generate" | jq '{response_type, summary, reference_symbols: .config.reference_symbols}'
```

- [ ] Strategy builder creates a VIX add/reduce draft with `response_type` of `CREATE_DRAFT`:

```bash
curl -fsS \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $DEV_USER_ID" \
  -d '{"prompt":"Buy and hold QQQ. Add when VIX is below 15. Reduce when VIX is above 35."}' \
  "$API_BASE/strategy-builder/generate" | jq '{response_type, summary, reference_symbols: .config.reference_symbols, position_management: .config.position_management}'
```

Optional local helper:

```bash
scripts/smoke_local_api.sh
```

## Product Loop

- [ ] In Strategy Chat, create a simple RSI draft such as: `Create a QQQ mean reversion strategy with RSI below 35 and exit when RSI is above 65.`
- [ ] Confirm the draft preview shows the expected symbol, entry rule, exit rule, date range, and warnings/assumptions.
- [ ] Create a VIX + RSI draft such as: `Only trade QQQ when VIX is below 25 and RSI is below 35.`
- [ ] Confirm the draft includes `VIX` as a reference symbol and combines VIX with RSI.
- [ ] Create a VIX add/reduce draft such as: `Buy and hold QQQ. Add when VIX is below 15. Reduce when VIX is above 35.`
- [ ] Confirm the draft includes core overlay and position management add/reduce behavior.
- [ ] Run a normal simulation from the current draft.
- [ ] Confirm the run queues, progresses, completes, and the run detail page loads with summary metrics and charts.
- [ ] Save the unsaved run as a strategy from the run detail page.
- [ ] Confirm Strategy Library shows the saved strategy.
- [ ] Open the strategy dashboard and confirm it shows the saved version and reference run.
- [ ] From the current draft, create a parameter sweep such as varying RSI thresholds or VIX add/reduce thresholds.
- [ ] Run the parameter sweep.
- [ ] Confirm sweep progress updates while variants run and ends in a completed state.
- [ ] Confirm sweep results rank variants and expose metrics for each variant.
- [ ] Open a variant review page from the sweep results.
- [ ] Compare one normal run result against one selected sweep variant result.
- [ ] Confirm comparison rejects the parameter sweep parent run if selected directly, and accepts typed sweep variant results.

## Protected Auth Check

Run this against a protected beta or production backend, not local dev. Protected environments must not trust `X-User-Id`; user-scoped routes should require a valid bearer JWT when `AUTH_MODE=oidc` is configured.

- [ ] Provision the beta tester with an external identity subject when known:

```bash
python scripts/provision_user.py --email user@example.com --display-name "User Name" --plan-code FREE --external-provider oidc --external-subject abc123
```

- [ ] If the subject is not known before first login, confirm `OIDC_ALLOW_EMAIL_LINKING=true` and provision the tester email as a temporary bootstrap path:

```bash
python scripts/provision_user.py --email user@example.com --display-name "User Name" --plan-code FREE
```

```bash
PROTECTED_API_BASE=https://your-beta-api.example.com
curl -i \
  -H "X-User-Id: 00000000-0000-0000-0000-000000000001" \
  "$PROTECTED_API_BASE/me/entitlements"
```

- [ ] Confirm the response status is `401`.
- [ ] Confirm the response is `401`; with OIDC configured, the body should report a missing bearer token, not accept `X-User-Id`.

## Release Gate

- [ ] Backend tests pass:

```bash
pytest
```

- [ ] Frontend build passes:

```bash
cd frontend
npm run build
cd ..
```
