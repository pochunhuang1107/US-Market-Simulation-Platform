#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<USAGE
Usage: $0 [--help]

Runs the local/code beta release gate. The gate is safe to run locally: it does
not require real secrets, print env values, create cloud resources, or start the
compose stack.
USAGE
}

section() {
  printf '\n== %s ==\n' "$1"
}

pass() {
  printf 'PASS %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "missing required command: $1"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

section "Prerequisites"
need_cmd git
need_cmd python
need_cmd npm
need_cmd docker
if ! docker compose version >/dev/null 2>&1; then
  fail "missing required command: docker compose"
fi
pass "required commands are available"

section "Tracked Env Safety"
tracked_env_files="$(git ls-files | grep -E '(^|/)\.env($|\.)' | grep -Ev '(^|/)\.env(\.beta)?\.example$' || true)"
if [[ -n "$tracked_env_files" ]]; then
  printf 'Tracked real env files are release blockers:\n%s\n' "$tracked_env_files" >&2
  exit 1
fi
pass "no real env files are tracked"

section "Beta Env Template Preflight"
python scripts/beta_preflight.py \
  --backend-env .env.beta.example \
  --frontend-env frontend/.env.beta.example \
  --target-env beta

section "Docker Compose Config"
docker compose -f docker-compose.beta-local.yml config >/dev/null
pass "docker-compose.beta-local.yml parses successfully"

section "Frontend Route Split"
router_source="frontend/src/router.tsx"
grep -F "path: '/'," "$router_source" >/dev/null
grep -F "element: <LandingPage />" "$router_source" >/dev/null
grep -F "{ path: '/workspace', element: <StrategyChatPage /> }" "$router_source" >/dev/null
grep -F "{ path: '/chat', element: <Navigate to=\"/workspace\" replace /> }" "$router_source" >/dev/null
pass "/ is landing, /workspace is the app, and legacy /chat redirects"

section "Backend Tests"
pytest

section "Frontend Build"
npm --prefix frontend run build

printf '\nPASS beta release gate completed.\n'
