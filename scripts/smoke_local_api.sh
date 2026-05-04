#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
DEV_USER_ID="${DEV_USER_ID:-00000000-0000-0000-0000-000000000001}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

get_json() {
  local path="$1"
  curl -fsS -H "X-User-Id: ${DEV_USER_ID}" "${API_BASE}${path}"
}

post_builder_prompt() {
  local prompt="$1"
  curl -fsS \
    -H "Content-Type: application/json" \
    -H "X-User-Id: ${DEV_USER_ID}" \
    -d "{\"prompt\":$(jq -Rn --arg prompt "$prompt" '$prompt')}" \
    "${API_BASE}/strategy-builder/generate"
}

expect_response_type() {
  local label="$1"
  local expected="$2"
  local body="$3"
  local actual

  actual="$(jq -r '.response_type // empty' <<<"$body")"
  if [[ "$actual" != "$expected" ]]; then
    echo "${label}: expected response_type=${expected}, got ${actual:-<missing>}" >&2
    jq . <<<"$body" >&2
    exit 1
  fi
}

need_cmd curl
need_cmd jq

echo "Checking backend health at ${API_BASE}"
health_body="$(curl -fsS "${API_BASE}/health")"
if [[ "$(jq -r '.status // empty' <<<"$health_body")" != "ok" ]]; then
  echo "Health check did not return status=ok" >&2
  jq . <<<"$health_body" >&2
  exit 1
fi

echo "Checking local dev entitlements for ${DEV_USER_ID}"
entitlements_body="$(get_json "/me/entitlements")"
if [[ "$(jq -r '.plan.code // empty' <<<"$entitlements_body")" == "" ]]; then
  echo "Entitlements response did not include plan.code" >&2
  jq . <<<"$entitlements_body" >&2
  exit 1
fi

echo "Checking VIX + RSI strategy builder draft"
vix_rsi_body="$(post_builder_prompt "Only trade QQQ when VIX is below 25 and RSI is below 35.")"
expect_response_type "VIX + RSI draft" "CREATE_DRAFT" "$vix_rsi_body"
if [[ "$(jq -r '.config.reference_symbols | index("VIX") != null' <<<"$vix_rsi_body")" != "true" ]]; then
  echo "VIX + RSI draft did not include VIX as a reference symbol" >&2
  jq . <<<"$vix_rsi_body" >&2
  exit 1
fi

echo "Checking VIX add/reduce strategy builder draft"
add_reduce_body="$(post_builder_prompt "Buy and hold QQQ. Add when VIX is below 15. Reduce when VIX is above 35.")"
expect_response_type "VIX add/reduce draft" "CREATE_DRAFT" "$add_reduce_body"
if [[ "$(jq -r '.config.position_management != null' <<<"$add_reduce_body")" != "true" ]]; then
  echo "VIX add/reduce draft did not include position_management" >&2
  jq . <<<"$add_reduce_body" >&2
  exit 1
fi

echo "Local API smoke passed."
