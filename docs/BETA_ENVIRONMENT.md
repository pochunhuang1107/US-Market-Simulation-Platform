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
- Requests must have a real authenticated `current_user` context from the auth boundary. Beta and production must not trust client-provided `X-User-Id`.
- Until a real auth provider is integrated, protected environments return `401` with `Authenticated user provider is not configured.` for user-scoped routes.
- Use a durable Postgres database in `DATABASE_URL`.
- Use S3 artifact storage for persisted run outputs.

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

## Verification

Run these before promoting beta environment changes:

```bash
pytest
cd frontend
npm run build
```

For a concise manual product-loop pass, use [Beta Smoke Checklist](BETA_SMOKE_CHECKLIST.md).
