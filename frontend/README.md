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

Local development uses the existing dev/manual bearer-token behavior when `VITE_AUTH_PROVIDER` is unset or set to `dev`.

For beta Auth0 Universal Login, set these Vite-safe variables in the frontend environment:

```bash
VITE_AUTH_PROVIDER=auth0
VITE_AUTH0_DOMAIN=your-tenant.region.auth0.com
VITE_AUTH0_CLIENT_ID=your-spa-client-id
VITE_AUTH0_AUDIENCE=your-api-audience
# VITE_AUTH0_REDIRECT_URI=https://your-frontend.example.com
```

The Auth0 SDK keeps its token cache internally. The older `localStorage.market_simulator_access_token` helper remains dev-only/manual testing support.

## Included pages

- `/runs`
- `/runs/:runId`
- `/compare`
- `/strategies/:strategyId`
