# Beta Environment

This app has separate expectations for local development and protected beta or production environments.

## Local Development

- `ENV=local` with `AUTH_MODE=dev` is acceptable for local development and tests.
- A copied `.env.example` should run locally with minimal edits if the default Postgres URL matches your local database.
- `DEV_DEFAULT_USER_ID`, `DEV_ADMIN_USER_IDS`, and `X-User-Id` are development conveniences only.
- `ENABLE_DEV_ADMIN_OVERRIDE=false` is the default. Enable it only for local entitlement/admin testing.
- `ARTIFACT_STORAGE_BACKEND=LOCAL` is the default and writes run artifacts under `ARTIFACTS_DIR`.
- Local data access should still point at curated app-ready datasets, not raw market-data inputs.

## Beta And Production

- Use `ENV=beta` or `ENV=production`.
- Do not use dev auth in protected environments. The app resolves beta and production auth as required even if `AUTH_MODE=dev` is configured.
- Use `AUTH_MODE=oidc` to validate `Authorization: Bearer <JWT>` against an OIDC-compatible provider. `AUTH_MODE=required` also enables OIDC when `OIDC_JWKS_URL` is configured.
- Beta and production must not trust client-provided `X-User-Id`; that header remains local/dev/test only.
- Configure the OIDC issuer metadata used by the backend:
  - `OIDC_JWKS_URL` is required for OIDC mode and should point to the provider JWKS endpoint.
  - `OIDC_ISSUER` is optional but recommended; when set, the JWT `iss` claim must match exactly.
  - `OIDC_AUDIENCE` is optional but recommended; when set, the JWT `aud` claim must include this value.
  - `OIDC_EMAIL_CLAIM` defaults to `email`.
  - `OIDC_SUBJECT_CLAIM` defaults to `sub`.
  - `OIDC_DISPLAY_NAME_CLAIM` defaults to `name`.
- The MVP maps validated tokens to existing app users by email. Users must already exist in the app database before beta access is granted; automatic onboarding can be added later.
- Provision OIDC beta users by email before their first login. The email in the OIDC token must match the app user email after lowercase normalization.

```bash
python scripts/provision_user.py --email user@example.com --display-name "User Name" --plan-code FREE
```

- Re-running the provisioning command is idempotent. Existing users keep their current status unless `--status` or `--deactivate` is explicitly provided.
- There is no external subject/provider column yet, so changing a user's email at the identity provider can break mapping until the app schema gains provider subject binding.
- If OIDC is not configured, protected environments return `401` with `Authenticated user provider is not configured.` for user-scoped routes.
- Use a durable Postgres database in `DATABASE_URL`.
- Use S3 artifact storage for persisted run outputs.

## Frontend Bearer Tokens

- The React API client attaches `Authorization: Bearer <token>` only when a frontend access token is available.
- Local development remains unchanged: `ENV=local` with `AUTH_MODE=dev` can still use the backend dev-auth defaults and does not require a browser token.
- Protected beta frontend deployments must obtain an access token from the future auth provider and supply it through the frontend token provider boundary. No provider SDK or login redirect flow is wired in yet.
- For manual beta API-client testing, developers can set `localStorage.market_simulator_access_token` in the browser. The helper also exposes `setAccessTokenForDevelopment(token)` and `clearAccessToken()` for console-driven testing.
- The frontend now shows an auth-required state when `/api/me/entitlements` returns `401`, preserving the backend response and allowing testers to clear a saved local token and retry. Real login-provider UI remains future work.

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

`SUPPORTED_DATA_END_DATE` is optional. When omitted, the app defaults it to today's date.

## Readiness Preflight

Use `GET /health/readiness` before beta testing to verify the deployed environment without exposing secrets or requiring AWS credentials. The endpoint always returns HTTP 200 and includes `overall_status` plus structured checks for app environment, resolved auth mode, database connectivity, artifact storage configuration, curated data paths, and supported ETF/reference-series symbol counts.

Treat `overall_status=ready` as the expected beta starting point. Investigate `warning` or `not_ready` checks before testers begin, especially placeholder curated-data paths, missing `OIDC_JWKS_URL` in protected environments, or missing `ARTIFACT_S3_BUCKET` when S3 artifact storage is selected.

## Verification

Run these before promoting beta environment changes:

```bash
pytest
cd frontend
npm run build
```

For a concise manual product-loop pass, use [Beta Smoke Checklist](BETA_SMOKE_CHECKLIST.md).
