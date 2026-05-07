# Beta Environment

This app has separate expectations for local development and protected beta or production environments.

## Local Development

- `ENV=local` with `AUTH_MODE=dev` is acceptable for local development and tests.
- A copied `.env.example` should run locally with minimal edits if the default Postgres URL matches your local database.
- `DEV_DEFAULT_USER_ID`, `DEV_ADMIN_USER_IDS`, and `X-User-Id` are development conveniences only.
- The frontend stays in local/manual token mode when `VITE_AUTH_PROVIDER` is unset or set to `dev`.
- `ENABLE_DEV_ADMIN_OVERRIDE=false` is the default. Enable it only for local entitlement/admin testing.
- `ARTIFACT_STORAGE_BACKEND=LOCAL` is the default and writes run artifacts under `ARTIFACTS_DIR`.
- Local data access should still point at curated app-ready datasets, not raw market-data inputs.

## Beta And Production

- Use `ENV=beta` or `ENV=production`.
- Do not use dev auth in protected environments. The app resolves beta and production auth as required even if `AUTH_MODE=dev` is configured.
- Do not use `DEV_ADMIN` override in beta or protected environments. Invited founder and QA accounts should use the DB-backed `BETA_TESTER` plan instead.
- Use `AUTH_MODE=oidc` to validate `Authorization: Bearer <JWT>` against an OIDC-compatible provider. `AUTH_MODE=required` also enables OIDC when `OIDC_JWKS_URL` is configured.
- Beta and production must not trust client-provided `X-User-Id`; that header remains local/dev/test only.
- Configure the OIDC issuer metadata used by the backend:
  - `OIDC_JWKS_URL` is required for OIDC mode and should point to the provider JWKS endpoint.
  - `OIDC_ISSUER` is optional but recommended; when set, the JWT `iss` claim must match exactly.
  - `OIDC_AUDIENCE` is optional but recommended; when set, the JWT `aud` claim must include this value.
  - `OIDC_EMAIL_CLAIM` defaults to `email`.
  - `OIDC_SUBJECT_CLAIM` defaults to `sub`.
  - `OIDC_DISPLAY_NAME_CLAIM` defaults to `name`.
  - `OIDC_PROVIDER_NAME` defaults to `oidc` and is stored with the token subject when linking an external identity. Use `auth0` for Auth0-specific beta identity links, or `oidc` for provider-neutral links.
  - `OIDC_ALLOW_EMAIL_LINKING` defaults to `true` for the beta MVP. When enabled, the first valid OIDC login for a provisioned email can create the durable provider+subject link. Set it to `false` once beta users are pre-linked by subject.
- The preferred OIDC mapping is durable provider+subject identity, for example `provider=oidc` plus the JWT `sub` claim. Email is only a bootstrap fallback for provisioned users.
- Users must already exist in the app database before beta access is granted; automatic onboarding is intentionally not enabled.
- `BETA_TESTER` is the zero-dollar plan for invited beta/founder QA accounts. It keeps beta access explicit in the database and enables generous QA limits, parameter sweeps, comparison runs, portfolio runs, AI builder, and strategy history without relying on local development overrides.
- Auth0 backend example:

```bash
AUTH_MODE=oidc
OIDC_JWKS_URL=https://your-tenant.region.auth0.com/.well-known/jwks.json
OIDC_ISSUER=https://your-tenant.region.auth0.com/
OIDC_AUDIENCE=your-api-audience
OIDC_PROVIDER_NAME=auth0
```

- Provision OIDC beta users with the external provider and subject when those values are known:

```bash
python scripts/provision_user.py --email user@example.com --display-name "User Name" --plan-code BETA_TESTER --external-provider oidc --external-subject abc123
```

- Provision Auth0 beta users with the Auth0 subject when available:

```bash
python scripts/provision_user.py \
  --email user@example.com \
  --display-name "User Name" \
  --plan-code BETA_TESTER \
  --external-provider auth0 \
  --external-subject "auth0-or-social-provider|subject"
```

- If the provider subject is not known yet, provision by email and allow the first valid login to link the subject while `OIDC_ALLOW_EMAIL_LINKING=true`:

```bash
python scripts/provision_user.py --email user@example.com --display-name "User Name" --plan-code BETA_TESTER
```

- Re-running the provisioning command is idempotent. Existing users keep their current status unless `--status` or `--deactivate` is explicitly provided.
- Email fallback linking depends on the token email matching an existing app user after lowercase normalization. It should be treated as a migration bridge, not the long-term account binding.
- If OIDC is not configured, protected environments return `401` with `Authenticated user provider is not configured.` for user-scoped routes.
- Use a durable Postgres database in `DATABASE_URL`.
- Use S3 artifact storage for persisted run outputs.
- Use `.env.beta.example` and `frontend/.env.beta.example` as placeholder-only templates for protected beta configuration. Do not commit copied real env files.

## Frontend Bearer Tokens

- The React API client attaches `Authorization: Bearer <token>` only when a frontend access token is available.
- Local development remains unchanged: `ENV=local` with `AUTH_MODE=dev` can still use the backend dev-auth defaults and does not require a browser token.
- Protected beta frontend deployments should use Auth0 Universal Login through the Auth0 React SDK:

```bash
VITE_AUTH_PROVIDER=auth0
VITE_AUTH0_DOMAIN=your-tenant.region.auth0.com
VITE_AUTH0_CLIENT_ID=your-spa-client-id
VITE_AUTH0_AUDIENCE=your-api-audience
# Optional when the deployed callback differs from window.location.origin:
VITE_AUTH0_REDIRECT_URI=https://your-frontend.example.com
# Optional session persistence controls. Defaults are shown:
VITE_AUTH0_CACHE_LOCATION=memory
VITE_AUTH0_USE_REFRESH_TOKENS=false
```

- In Auth0 mode, the frontend shows sign-in and sign-out controls, acquires access tokens silently with the SDK, and passes them through the existing bearer-token request boundary.
- `VITE_AUTH0_CACHE_LOCATION=memory` is the default and keeps tokens out of persistent browser storage. It is safer, but after a browser refresh the SDK may need silent auth, and some tenant/session settings may require the user to sign in again.
- `VITE_AUTH0_CACHE_LOCATION=localstorage` can improve refresh persistence, but it stores Auth0 tokens in browser local storage and should be enabled only when that security tradeoff is intentional. `VITE_AUTH0_USE_REFRESH_TOKENS=true` should only be used with the matching Auth0 tenant/application refresh-token settings.
- For manual local or API-client testing only, developers can set `localStorage.market_simulator_access_token` in the browser. The helper also exposes `setAccessTokenForDevelopment(token)` and `clearAccessToken()` for console-driven testing.
- The auth-required state shows a Sign in action in Auth0 mode, preserves backend `401` responses, and still allows testers to clear a saved manual dev token and retry when applicable.

## Curated Data Paths

The app should read curated ETF and reference-series paths only:

- ETF prices: `MARKET_DATA_PATH=s3://your-market-data-bucket/curated/etf_daily_prices/**/*.parquet`
- ETF metadata: `ETF_METADATA_S3_URI=s3://your-market-data-bucket/curated/reference/etf_symbol_metadata/data.parquet`
- Reference-series data: `REFERENCE_SERIES_DATA_PATH=s3://your-market-data-bucket/curated/reference_series`
- Reference-series metadata: `REFERENCE_SERIES_METADATA_S3_URI=s3://your-market-data-bucket/curated/reference/reference_series_metadata/data.parquet`

Use a private market-data bucket in local `.env` or protected environment configuration. Committed examples intentionally use placeholder bucket names.

## Artifact Storage

- Local development: `ARTIFACT_STORAGE_BACKEND=LOCAL` and `ARTIFACTS_DIR=./data/local_artifacts`.
- Beta/production: `ARTIFACT_STORAGE_BACKEND=S3` with `ARTIFACT_S3_BUCKET`, `ARTIFACT_S3_PREFIX`, `ARTIFACT_S3_REGION`, and `ARTIFACT_PRESIGN_TTL_SECONDS` configured.
- Changing `ARTIFACT_STORAGE_BACKEND` affects new runs only. Existing runs continue to reference the artifact storage recorded when they executed. In S3 mode, the Results list defaults to S3-backed runs; use the storage filter to include old local runs when needed.
- Before beta sign-off, run at least one parameter sweep with S3 artifact storage enabled and verify the sweep result page, variant detail chart data, comparison between selected variants, and promote/edit-as-version flow. Sweep summaries and result rows should reference S3 artifact directories for variants, not local worker paths.

`SUPPORTED_DATA_END_DATE` is optional. When omitted, the app defaults it to today's date.

## Readiness Preflight

Use `GET /health/readiness` before beta testing to verify the deployed environment without exposing secrets or requiring AWS credentials. The endpoint always returns HTTP 200 and includes `overall_status` plus structured checks for app environment, resolved auth mode, database connectivity, artifact storage configuration, curated data paths, and supported ETF/reference-series symbol counts.

Treat `overall_status=ready` as the expected beta starting point. Investigate `warning` or `not_ready` checks before testers begin, especially placeholder curated-data paths, missing `OIDC_JWKS_URL` in protected environments, local artifact storage in beta/prod, or missing `ARTIFACT_S3_BUCKET` when S3 artifact storage is selected.

Use the static preflight before startup or image promotion when you only need config-shape checks:

```bash
python scripts/beta_preflight.py \
  --backend-env .env.beta \
  --frontend-env frontend/.env.beta \
  --target-env beta
```

## Verification

Run these before promoting beta environment changes:

```bash
pytest
cd frontend
npm run build
```

For a concise manual product-loop pass, use [Beta Smoke Checklist](BETA_SMOKE_CHECKLIST.md).
