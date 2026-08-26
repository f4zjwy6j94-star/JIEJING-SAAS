#!/usr/bin/env bash
set -euo pipefail

PRODUCTION_ROOT="/opt/jiejing-production"
ACTIVE_LINK="$PRODUCTION_ROOT/app"
RELEASE_ROOT="$PRODUCTION_ROOT/releases"
COMPOSE_NAME="docker-compose.production-pilot.yml"
LOCK_FILE="/run/lock/jiejing-production-maintenance.lock"
PUBLIC_BASE_URL="https://app.jiejing.shop"

fail_closed() {
  printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=blocked"
  printf 'JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=%s\n' "$1"
  exit 2
}

canonical_path_equals() {
  local candidate="$1" expected="$2" candidate_resolved expected_resolved
  candidate_resolved="$(readlink -f -- "$candidate" 2>/dev/null || true)"
  expected_resolved="$(readlink -f -- "$expected" 2>/dev/null || true)"
  [[ -n "$candidate_resolved" && "$candidate_resolved" == "$expected_resolved" ]]
}

acquire_nonblocking_lock() {
  local path="$1" flock_rc
  command -v flock >/dev/null 2>&1 || return 11
  if ! exec 9>"$path"; then
    return 11
  fi
  if flock -n 9; then
    flock_rc=0
  else
    flock_rc=$?
  fi
  case "$flock_rc" in
    0) return 0 ;;
    1) return 10 ;;
    *) return 11 ;;
  esac
}

trusted_private_file() {
  local path="$1" resolved metadata
  [[ -f "$path" && ! -L "$path" ]] || return 1
  resolved="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ "$resolved" == "$path" ]] || return 1
  metadata="$(stat -c '%U:%G %a' -- "$path" 2>/dev/null || true)"
  [[ "$metadata" == "root:root 600" ]]
}

trusted_private_directory() {
  local path="$1" metadata owner mode
  [[ -d "$path" && ! -L "$path" ]] || return 1
  metadata="$(stat -c '%U:%G %a' -- "$path" 2>/dev/null || true)"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "root:root" && "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
  (( (8#$mode & 0022) == 0 ))
}

evidence_excluded_env_digest() {
  python3 - "$1" <<'PY'
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

EVIDENCE_FIELDS = {
    "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
}

path = Path(sys.argv[1])
filtered: list[bytes] = []
for line in path.read_bytes().splitlines(keepends=True):
    candidate = line.strip()
    if candidate and not candidate.startswith(b"#") and b"=" in candidate:
        key = candidate.split(b"=", 1)[0].strip().decode("ascii", errors="strict")
        if key in EVIDENCE_FIELDS:
            continue
    filtered.append(line)
print(hashlib.sha256(b"".join(filtered)).hexdigest())
PY
}

json_contract_verified() {
  local contract="$1"
  python3 -c '
from __future__ import annotations

import json
import sys

contract = sys.argv[1]
try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError, UnicodeError):
    raise SystemExit(2)

common = (
    isinstance(payload, dict)
    and payload.get("status") == "verified"
    and payload.get("verification_evidence_recorded") is True
    and payload.get("secret_exposed") is False
)
if contract == "cos":
    verified = (
        common
        and set(payload) == {
            "status",
            "contract_version",
            "probe_verified",
            "verification_evidence_recorded",
            "secret_exposed",
        }
        and payload.get("contract_version") == "jiejing_cos_backup_probe_v1"
        and payload.get("probe_verified") is True
    )
elif contract == "cls":
    verified = (
        common
        and set(payload) == {
            "status",
            "probe_uploaded",
            "probe_searchable",
            "alarm_queries_exclude_probe",
            "event_field_count",
            "event_allowlist_exact",
            "notification_test_sent",
            "resource_ids_exposed",
            "secret_exposed",
            "verification_evidence_recorded",
        }
        and payload.get("probe_uploaded") is True
        and payload.get("probe_searchable") is True
        and payload.get("alarm_queries_exclude_probe") is True
        and type(payload.get("event_field_count")) is int
        and payload.get("event_field_count") == 12
        and payload.get("event_allowlist_exact") is True
        and payload.get("notification_test_sent") is False
        and payload.get("resource_ids_exposed") is False
    )
else:
    verified = False
raise SystemExit(0 if verified else 2)
' "$contract"
}

public_health_ready() {
  local body
  body="$(curl -fsS --max-time 15 -A 'Mozilla/5.0 JiejingProductionEvidenceRefresh/1.0' \
    "$PUBLIC_BASE_URL/health" 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError, UnicodeError):
    raise SystemExit(2)
ready = (
    payload.get("status") == "ok"
    and payload.get("database_startup_status") == "ready"
    and payload.get("real_platform_writes_enabled") is False
    and payload.get("requested_real_platform_writes") is False
    and payload.get("secret_exposed") is False
)
raise SystemExit(0 if ready else 2)
' <<<"$body" >/dev/null 2>&1
}

public_deep_health_ready() {
  local body
  body="$(curl -fsS --max-time 15 -A 'Mozilla/5.0 JiejingProductionEvidenceRefresh/1.0' \
    "$PUBLIC_BASE_URL/health/deep" 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError, UnicodeError):
    raise SystemExit(2)
operational = payload.get("operational_health") or {}
ready = (
    operational.get("status") == "ready"
    and operational.get("database", {}).get("status") == "ready"
    and operational.get("queue", {}).get("status") == "ready"
    and operational.get("worker", {}).get("status") == "ready"
    and operational.get("secret_exposed") is False
)
raise SystemExit(0 if ready else 2)
' <<<"$body" >/dev/null 2>&1
}

public_readiness_ready() {
  local body
  body="$(curl -fsS --max-time 20 -A 'Mozilla/5.0 JiejingProductionEvidenceRefresh/1.0' \
    "$PUBLIC_BASE_URL/readiness/product-saas" 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError, UnicodeError):
    raise SystemExit(2)
readiness = payload.get("readiness") or {}
items = readiness.get("items") or []
if any(not isinstance(item, dict) for item in items):
    raise SystemExit(2)
item_by_key = {item.get("key"): item for item in items}
providers = readiness.get("provider_status") or {}
backup = providers.get("backup") or {}
billing = providers.get("billing") or {}
ready = (
    readiness.get("blocker_count") == 0
    and readiness.get("beta_ready") is True
    and readiness.get("production_ready") is False
    and readiness.get("can_accept_real_customers") is False
    and readiness.get("real_platform_writes_enabled") is False
    and readiness.get("requested_real_platform_writes") is False
    and readiness.get("secret_exposed") is False
    and backup.get("backup_ready_for_paid_launch") is True
    and backup.get("blockers") == []
    and backup.get("secret_exposed") is False
    and "backup_restore" not in item_by_key
    and "monitoring_alerting" not in item_by_key
    and billing.get("public_charging_allowed") is False
    and billing.get("charge_now_allowed") is False
    and billing.get("triggers_real_charge") is False
    and billing.get("triggers_real_refund") is False
    and billing.get("real_platform_writes_enabled") is False
    and billing.get("secret_exposed") is False
)
raise SystemExit(0 if ready else 2)
' <<<"$body" >/dev/null 2>&1
}

wait_for_api_health() {
  local container_id state health attempt
  for attempt in $(seq 1 60); do
    container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-saas 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      state="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"
      if [[ "$state" == "running" && "$health" == "healthy" ]] && public_health_ready; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

wait_for_worker_health() {
  local container_id state attempt
  for attempt in $(seq 1 60); do
    container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-worker 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      state="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
      if [[ "$state" == "running" ]] && public_deep_health_ready; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

approved_image_reference_matches() {
  local image_reference="$1" approved_image_id="$2" resolved_image_id
  resolved_image_id="$(docker image inspect --format '{{.Id}}' "$image_reference" 2>/dev/null || true)"
  [[ "$resolved_image_id" == "$approved_image_id" ]]
}

capture_and_validate_runtime_images() {
  mapfile -t api_containers < <(
    docker ps \
      --filter 'label=com.docker.compose.project=deploy' \
      --filter 'label=com.docker.compose.service=jiejing-saas' \
      --format '{{.ID}}'
  )
  [[ "${#api_containers[@]}" -eq 1 ]] || fail_closed "runtime_api_container_not_unique"
  approved_api_container_id="${api_containers[0]}"

  runtime_api_project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_service="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_config_files="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_project_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_environment_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_image_id="$(docker inspect --format '{{.Image}}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_image_ref="$(docker inspect --format '{{.Config.Image}}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_state="$(docker inspect --format '{{.State.Status}}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$approved_api_container_id" 2>/dev/null || true)"

  [[ "$runtime_api_project" == "deploy" && "$runtime_api_service" == "jiejing-saas" ]] \
    || fail_closed "runtime_compose_label_mismatch"
  canonical_path_equals "$runtime_api_config_files" "$runtime_compose" \
    || fail_closed "runtime_compose_label_mismatch"
  canonical_path_equals "$runtime_api_project_dir" "$active_app/deploy" \
    || fail_closed "runtime_compose_label_mismatch"
  [[ "$runtime_api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail_closed "runtime_api_image_untrusted"
  docker image inspect "$runtime_api_image_id" >/dev/null 2>&1 \
    || fail_closed "runtime_api_image_untrusted"
  approved_image_reference_matches "$runtime_api_image_ref" "$runtime_api_image_id" \
    || fail_closed "api_image_reference_drift"
  [[ "$runtime_api_state" == "running" && "$runtime_api_health" == "healthy" ]] \
    || fail_closed "runtime_api_container_unhealthy"

  mapfile -t worker_containers < <(
    docker ps \
      --filter 'label=com.docker.compose.project=deploy' \
      --filter 'label=com.docker.compose.service=jiejing-worker' \
      --format '{{.ID}}'
  )
  [[ "${#worker_containers[@]}" -eq 1 ]] || fail_closed "runtime_worker_container_not_unique"
  approved_worker_container_id="${worker_containers[0]}"
  runtime_worker_project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_service="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_config_files="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_project_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_environment_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_image_id="$(docker inspect --format '{{.Image}}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_image_ref="$(docker inspect --format '{{.Config.Image}}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_state="$(docker inspect --format '{{.State.Status}}' "$approved_worker_container_id" 2>/dev/null || true)"

  [[ "$runtime_worker_project" == "deploy" && "$runtime_worker_service" == "jiejing-worker" ]] \
    || fail_closed "runtime_worker_compose_label_mismatch"
  canonical_path_equals "$runtime_worker_config_files" "$runtime_compose" \
    || fail_closed "runtime_worker_compose_label_mismatch"
  canonical_path_equals "$runtime_worker_project_dir" "$active_app/deploy" \
    || fail_closed "runtime_worker_compose_label_mismatch"
  [[ "$runtime_worker_environment_file" == "$runtime_api_environment_file" ]] \
    || fail_closed "runtime_environment_label_mismatch"
  [[ "$runtime_worker_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail_closed "runtime_worker_image_untrusted"
  docker image inspect "$runtime_worker_image_id" >/dev/null 2>&1 \
    || fail_closed "runtime_worker_image_untrusted"
  approved_image_reference_matches "$runtime_worker_image_ref" "$runtime_worker_image_id" \
    || fail_closed "worker_image_reference_drift"
  [[ "$runtime_worker_state" == "running" ]] \
    || fail_closed "runtime_worker_image_untrusted"
  public_deep_health_ready \
    || fail_closed "runtime_worker_operational_unhealthy"

  environment_file="$runtime_api_environment_file"
}

run_cos_probe() {
  local cos_output env_digest_after
  cos_output="$(docker run --rm --network bridge \
    --mount "type=bind,src=$private_dir,dst=/private" \
    -w /app "$runtime_api_image_id" python tools/jiejing_configure_tencent_runtime_env.py \
    --env-file /private/jiejing-saas.production.env \
    --verify-cos-backup-probe --apply 2>/dev/null)" || {
    LAST_BLOCKER="cos_probe_failed"
    return 2
  }
  if ! json_contract_verified cos <<<"$cos_output" >/dev/null 2>&1; then
    unset cos_output
    LAST_BLOCKER="cos_probe_contract_rejected"
    return 2
  fi
  unset cos_output
  if ! trusted_private_file "$APP_ENV"; then
    LAST_BLOCKER="private_env_permissions_untrusted"
    return 2
  fi
  env_digest_after="$(evidence_excluded_env_digest "$APP_ENV")" || {
    LAST_BLOCKER="private_env_digest_failed"
    return 2
  }
  if [[ "$env_digest_after" != "$env_digest_before" ]]; then
    LAST_BLOCKER="environment_drift_detected"
    return 2
  fi
  printf '%s\n' "COS_PROBE_STATUS=verified"
}

run_cls_probe() {
  local cls_output env_digest_after
  cls_output="$(docker run --rm --network bridge \
    --mount "type=bind,src=$private_dir,dst=/private" \
    -w /app "$runtime_api_image_id" python tools/jiejing_configure_tencent_runtime_env.py \
    --env-file /private/jiejing-saas.production.env \
    --verify-provider-cls-probe --apply 2>/dev/null)" || {
    LAST_BLOCKER="cls_probe_failed"
    return 2
  }
  if ! json_contract_verified cls <<<"$cls_output" >/dev/null 2>&1; then
    unset cls_output
    LAST_BLOCKER="cls_probe_contract_rejected"
    return 2
  fi
  unset cls_output
  if ! trusted_private_file "$APP_ENV"; then
    LAST_BLOCKER="private_env_permissions_untrusted"
    return 2
  fi
  env_digest_after="$(evidence_excluded_env_digest "$APP_ENV")" || {
    LAST_BLOCKER="private_env_digest_failed"
    return 2
  }
  if [[ "$env_digest_after" != "$env_digest_before" ]]; then
    LAST_BLOCKER="environment_drift_detected"
    return 2
  fi
  printf '%s\n' "CLS_PROBE_STATUS=verified"
}

recreate_api() {
  if ! approved_image_reference_matches "$runtime_api_image_ref" "$runtime_api_image_id"; then
    LAST_BLOCKER="api_image_reference_drift"
    return 2
  fi
  if ! docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-saas \
    >/dev/null 2>&1; then
    LAST_BLOCKER="api_recreate_failed"
    return 2
  fi
}

verify_recreated_api() {
  local new_api_container_id new_api_image_id
  if ! wait_for_api_health; then
    LAST_BLOCKER="api_health_failed"
    return 2
  fi
  new_api_container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-saas 2>/dev/null || true)"
  new_api_image_id="$(docker inspect --format '{{.Image}}' "$new_api_container_id" 2>/dev/null || true)"
  if ! [[ "$new_api_container_id" != "$approved_api_container_id" ]] \
    || ! [[ "$new_api_image_id" == "$runtime_api_image_id" ]]; then
    LAST_BLOCKER="api_identity_mismatch"
    return 2
  fi
}

recreate_worker() {
  if ! approved_image_reference_matches "$runtime_worker_image_ref" "$runtime_worker_image_id"; then
    LAST_BLOCKER="worker_image_reference_drift"
    return 2
  fi
  if ! docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-worker \
    >/dev/null 2>&1; then
    LAST_BLOCKER="worker_recreate_failed"
    return 2
  fi
}

verify_recreated_worker() {
  local new_worker_container_id new_worker_image_id
  if ! wait_for_worker_health; then
    LAST_BLOCKER="worker_health_failed"
    return 2
  fi
  new_worker_container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-worker 2>/dev/null || true)"
  new_worker_image_id="$(docker inspect --format '{{.Image}}' "$new_worker_container_id" 2>/dev/null || true)"
  if ! [[ "$new_worker_container_id" != "$approved_worker_container_id" ]] \
    || ! [[ "$new_worker_image_id" == "$runtime_worker_image_id" ]]; then
    LAST_BLOCKER="worker_identity_mismatch"
    return 2
  fi
}

reload_api_then_worker() {
  if ! recreate_api; then
    LAST_BLOCKER="${LAST_BLOCKER:-api_recreate_failed}"
    return 2
  fi
  if ! verify_recreated_api; then
    LAST_BLOCKER="${LAST_BLOCKER:-api_health_failed}"
    return 2
  fi
  printf '%s\n' "API_RELOAD_STATUS=ready"
  if ! recreate_worker; then
    LAST_BLOCKER="${LAST_BLOCKER:-worker_recreate_failed}"
    return 2
  fi
  if ! verify_recreated_worker; then
    LAST_BLOCKER="${LAST_BLOCKER:-worker_health_failed}"
    return 2
  fi
  printf '%s\n' "WORKER_RELOAD_STATUS=ready"
}

run_refresh_phases() {
  run_cos_probe || return $?
  run_cls_probe || return $?
  reload_api_then_worker || return $?
}

main() {
trap 'printf "%s\n" "SECRET_EXPOSED=false"' EXIT
[[ "$#" -eq 0 ]] || fail_closed "unexpected_arguments"

if acquire_nonblocking_lock "$LOCK_FILE" 2>/dev/null; then
  lock_rc=0
else
  lock_rc=$?
fi
case "$lock_rc" in
  0) ;;
  10)
    printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=skipped"
    printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=lock_busy"
    exit 0
    ;;
  *) fail_closed "maintenance_lock_failed" ;;
esac

[[ -L "$ACTIVE_LINK" ]] || fail_closed "active_release_untrusted"
[[ "$(stat -c '%U:%G' -- "$ACTIVE_LINK" 2>/dev/null || true)" == "root:root" ]] \
  || fail_closed "active_release_untrusted"
active_app="$(readlink -f -- "$ACTIVE_LINK" 2>/dev/null || true)"
case "$active_app" in
  "$RELEASE_ROOT"/*/app) ;;
  *) fail_closed "active_release_untrusted" ;;
esac
[[ -d "$active_app" ]] || fail_closed "active_release_untrusted"
runtime_compose="$active_app/deploy/$COMPOSE_NAME"
[[ -f "$runtime_compose" && ! -L "$runtime_compose" ]] || fail_closed "runtime_compose_untrusted"

capture_and_validate_runtime_images

environment_file_label="$environment_file"
environment_file="$(readlink -f -- "$environment_file_label" 2>/dev/null || true)"
[[ "$environment_file_label" == "$environment_file" ]] \
  || fail_closed "runtime_environment_label_mismatch"
private_dir="$(dirname -- "$environment_file")"
private_dir="$(readlink -f -- "$private_dir" 2>/dev/null || true)"
case "$private_dir" in
  "$PRODUCTION_ROOT/private"|"$RELEASE_ROOT"/*/private) ;;
  *) fail_closed "private_dir_untrusted" ;;
esac
trusted_private_directory "$private_dir" || fail_closed "private_dir_untrusted"
COMPOSE_ENV="$private_dir/production-compose.env"
APP_ENV="$private_dir/jiejing-saas.production.env"
[[ "$environment_file" == "$private_dir/production-compose.env" ]] \
  || fail_closed "runtime_environment_label_mismatch"
trusted_private_file "$COMPOSE_ENV" || fail_closed "private_env_permissions_untrusted"
trusted_private_file "$APP_ENV" || fail_closed "private_env_permissions_untrusted"

env_digest_before="$(evidence_excluded_env_digest "$APP_ENV")" \
  || fail_closed "private_env_digest_failed"

export JIEJING_PRODUCTION_PRIVATE_DIR="$private_dir"
COMPOSE_ARGS=(--project-name deploy --env-file "$COMPOSE_ENV" -f "$runtime_compose")
LAST_BLOCKER=""

docker run --rm -w /app "$runtime_api_image_id" python -c \
  "from pathlib import Path; import sys; sys.exit(0 if Path('tools/jiejing_configure_tencent_runtime_env.py').is_file() else 2)" \
  >/dev/null 2>&1 || fail_closed "runtime_probe_tool_missing"
printf '%s\n' "LIVE_RELEASE_GUARD_STATUS=ready"

run_refresh_phases || fail_closed "${LAST_BLOCKER:-refresh_phase_failed}"

public_readiness_ready || fail_closed "public_readiness_contract_failed"
printf '%s\n' "READINESS_STATUS=verified"
printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
