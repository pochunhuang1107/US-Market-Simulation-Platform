# Ownership And Authorization Checklist

This checklist records the beta ownership convention for user-scoped backend resources.

## Current User Boundary

- Protected API routes resolve identity through `get_current_user`.
- Local development and tests may use dev auth with `DEV_DEFAULT_USER_ID` or `X-User-Id`.
- Beta and production resolve `AUTH_MODE=dev` to required auth and must not trust client-provided `X-User-Id`.
- OIDC/Auth0 mode maps bearer JWT claims to a provisioned app user through provider+subject, with email linking only as a bootstrap path for existing users.

## Protected Resources

- Runs: list, detail, progress, dashboard, chart data, trade events, sleeve chart, enqueue, cancel, save-strategy, parent-run creation, and strategy/version-backed creation are scoped to the current user.
- Parameter sweeps: parent runs, variant detail, variant trade events, variant promotion, and saved/promoted variant runs are scoped through the owning sweep run.
- Strategies: list, dashboard, archive, restore, version creation, reference runs, and tracked-strategy creation are scoped to the current user.
- Compare: normal run refs and sweep-variant refs are resolved through the current user; mixed-owner comparisons fail before artifacts are loaded.
- Artifacts: manifests, local paths, chart data, trade events, and S3 presigned URLs are only returned after the owning run or sweep variant is resolved for the current user.
- Entitlements and usage: `/me/entitlements`, daily run counts, saved/tracked strategy counts, and builder prompt usage are calculated for the current user only.
- Builder: `/strategy-builder/generate` records accepted and rejected prompt usage against the current user and applies only that user's plan limits.

## Error Convention

- Missing or invalid authentication returns `401`.
- Authenticated users without entitlement or admin permission receive `403`.
- Cross-owner resource access uses the existing hidden-existence convention and returns `404` such as `Run not found`, `Strategy not found`, or `Sweep run not found`.
- Routes must not generate artifact URLs, read artifact files, mutate resources, or increment another user's usage before ownership has been checked.

## Admin And Worker Caveat

- The worker process may recover stale runs across users because it is an internal background process.
- The HTTP `POST /runs/admin/recover-stale` route is local-dev-admin only. Beta and production operations should use the worker command path instead of exposing cross-user recovery to beta testers.

## Test Coverage

- `tests/api/test_auth_ownership_api.py` exercises two-user ownership boundaries for auth mode, runs, strategies, compare, sweeps/variants, artifacts, tracking, entitlements, and the local admin recovery route.
- Add new user-scoped endpoints to that file with owner, non-owner, list-filtering, and artifact/side-effect assertions before beta release.
