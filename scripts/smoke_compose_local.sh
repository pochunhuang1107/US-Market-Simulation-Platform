#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.beta-local.yml}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
DEV_USER_ID="${DEV_USER_ID:-00000000-0000-0000-0000-000000000001}"
DOWN_AFTER=0
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-120}"

usage() {
  cat <<USAGE
Usage: $0 [--down] [--help]

Environment:
  COMPOSE_FILE              Compose file to use. Defaults to docker-compose.beta-local.yml.
  API_BASE                  API base URL. Defaults to http://127.0.0.1:8000.
  DEV_USER_ID               Expected seeded dev user id.
  HEALTH_TIMEOUT_SECONDS    Seconds to wait for /health status=ok. Defaults to 120.

Options:
  --down                    Stop the compose stack after the smoke check.
  --help                    Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --down)
      DOWN_AFTER=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "FAIL missing required command: $1" >&2
    exit 1
  fi
}

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

print_logs() {
  echo
  echo "Compose service status:" >&2
  compose ps >&2 || true
  echo
  echo "Recent api logs:" >&2
  compose logs --tail=120 api >&2 || true
  echo
  echo "Recent worker logs:" >&2
  compose logs --tail=120 worker >&2 || true
}

fail() {
  echo "FAIL $*" >&2
  print_logs
  exit 1
}

cleanup() {
  if [[ "$DOWN_AFTER" == "1" ]]; then
    echo "Stopping compose stack without deleting volumes..."
    compose down
  fi
}
trap cleanup EXIT

need_cmd docker
need_cmd curl
need_cmd jq

if ! docker compose version >/dev/null 2>&1; then
  echo "FAIL missing required command: docker compose" >&2
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "FAIL compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

echo "Starting local compose stack with $COMPOSE_FILE..."
compose up --build -d || fail "docker compose up failed"

echo "Waiting for ${API_BASE}/health to return status=ok..."
deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
health_body=""
while (( SECONDS < deadline )); do
  if health_body="$(curl -fsS "${API_BASE}/health" 2>/dev/null)" \
    && [[ "$(jq -r '.status // empty' <<<"$health_body" 2>/dev/null)" == "ok" ]]; then
    echo "PASS /health status=ok"
    break
  fi
  sleep 2
done

if [[ "$(jq -r '.status // empty' <<<"${health_body:-{}}" 2>/dev/null)" != "ok" ]]; then
  fail "/health did not return status=ok within ${HEALTH_TIMEOUT_SECONDS}s"
fi

echo "Checking readiness..."
readiness_body="$(curl -fsS "${API_BASE}/health/readiness")" || fail "/health/readiness request failed"
readiness_status="$(jq -r '.overall_status // empty' <<<"$readiness_body")"
if [[ -z "$readiness_status" ]]; then
  echo "$readiness_body" | jq . >&2 || echo "$readiness_body" >&2
  fail "/health/readiness did not include overall_status"
fi
echo "PASS /health/readiness overall_status=${readiness_status}"
run_queue_status="$(jq -r '.checks.run_queue.status // empty' <<<"$readiness_body")"
if [[ -n "$run_queue_status" ]]; then
  queued_count="$(jq -r '.checks.run_queue.queued_count // 0' <<<"$readiness_body")"
  running_count="$(jq -r '.checks.run_queue.running_count // 0' <<<"$readiness_body")"
  stale_running_count="$(jq -r '.checks.run_queue.stale_running_count // 0' <<<"$readiness_body")"
  echo "PASS /health/readiness run_queue status=${run_queue_status} queued=${queued_count} running=${running_count} stale_running=${stale_running_count}"
  if [[ "$run_queue_status" == "not_ready" ]]; then
    echo "$readiness_body" | jq '.checks.run_queue' >&2 || echo "$readiness_body" >&2
    fail "/health/readiness run_queue is not_ready"
  fi
fi

echo "Checking seeded local dev entitlements..."
entitlements_body="$(curl -fsS -H "X-User-Id: ${DEV_USER_ID}" "${API_BASE}/me/entitlements")" \
  || fail "/me/entitlements request failed"

actual_user_id="$(jq -r '.user.id // empty' <<<"$entitlements_body")"
actual_plan_code="$(jq -r '.plan.code // empty' <<<"$entitlements_body")"

if [[ "$actual_user_id" != "$DEV_USER_ID" ]]; then
  echo "$entitlements_body" | jq . >&2 || echo "$entitlements_body" >&2
  fail "/me/entitlements user.id expected ${DEV_USER_ID}, got ${actual_user_id:-<missing>}"
fi

if [[ "$actual_plan_code" != "FREE" ]]; then
  echo "$entitlements_body" | jq . >&2 || echo "$entitlements_body" >&2
  fail "/me/entitlements plan.code expected FREE, got ${actual_plan_code:-<missing>}"
fi

echo "PASS /me/entitlements user.id=${actual_user_id} plan.code=${actual_plan_code}"
echo "Compose local smoke passed."

if [[ "$DOWN_AFTER" != "1" ]]; then
  echo "Stack left running. Stop it with: docker compose -f ${COMPOSE_FILE} down"
fi
