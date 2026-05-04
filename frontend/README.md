# US Market Strategy Frontend

Frontend package aligned to the existing backend contract.

## Start

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/runs`, `/strategies`, and `/health` to `http://127.0.0.1:8000`.

## Auth

Local development uses the existing dev/manual bearer-token behavior when `VITE_AUTH_PROVIDER` is unset or set to `dev`. This mode does not show the Auth0 sign-in controls.

For beta Auth0 Universal Login, set these Vite-safe variables in the frontend environment:

```bash
VITE_AUTH_PROVIDER=auth0
VITE_AUTH0_DOMAIN=your-tenant.region.auth0.com
VITE_AUTH0_CLIENT_ID=your-spa-client-id
VITE_AUTH0_AUDIENCE=your-api-audience
# VITE_AUTH0_REDIRECT_URI=https://your-frontend.example.com
# VITE_AUTH0_CACHE_LOCATION=memory
# VITE_AUTH0_USE_REFRESH_TOKENS=false
```

By default, Auth0 uses an in-memory token cache and refresh tokens are disabled. This is the safer default, but a browser refresh may require the SDK to perform silent auth or ask the user to sign in again depending on the tenant/session state.

Set `VITE_AUTH0_CACHE_LOCATION=localstorage` only when the deployment intentionally needs stronger refresh persistence. Local storage persists across reloads, but it increases exposure if browser JavaScript is compromised. `VITE_AUTH0_USE_REFRESH_TOKENS=true` can be paired with the Auth0 tenant settings when refresh-token rotation is configured.

For local Auth0 QA where refresh-token rotation is enabled in Auth0, use:

```bash
VITE_AUTH0_CACHE_LOCATION=localstorage
VITE_AUTH0_USE_REFRESH_TOKENS=true
```

The older `localStorage.market_simulator_access_token` helper remains dev-only/manual testing support.

## Included pages

- `/runs`
- `/runs/:runId`
- `/compare`
- `/strategies/:strategyId`
