#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/jiejing-staging/app"
DEPLOY_ROOT="/opt/jiejing-staging"
PRIVATE_DIR="$DEPLOY_ROOT/private"
MANAGED_ENV="$PRIVATE_DIR/tencent-managed.env"
OAUTH_ENV_PATH="$PRIVATE_DIR/jiejing-saas.staging-oauth.env"
POSTGRES_ENV="$PRIVATE_DIR/postgres-localqueue.env"
RELEASE_ROOT="$DEPLOY_ROOT/github-action-releases"
RUNTIME_COMPOSE="$APP_DIR/deploy/docker-compose.public-https-staging.yml"
TRUSTED_RUNTIME_ENV_GUARD="/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py"

trap 'echo "SECRET_EXPOSED=false"' EXIT

fail_closed() {
  echo "JIEJING_CLS_PROBE_AUTO_REFRESH_STATUS=blocked"
  echo "JIEJING_CLS_PROBE_AUTO_REFRESH_BLOCKER=$1"
  exit 2
}

trusted_root_owned_path_chain_is_safe() {
  local path="$1"
  local resolved current metadata owner mode
  [[ -f "$path" && ! -L "$path" ]] || return 1
  resolved="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ -n "$resolved" && "$resolved" == "$path" ]] || return 1
  metadata="$(stat -c '%u %a' -- "$path" 2>/dev/null || true)"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "0" && "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
  (( (8#$mode & 0022) == 0 )) || return 1

  current="$(dirname -- "$path")"
  while :; do
    [[ -d "$current" && ! -L "$current" ]] || return 1
    metadata="$(stat -c '%u %a' -- "$current" 2>/dev/null || true)"
    read -r owner mode <<<"$metadata"
    [[ "$owner" == "0" && "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
    (( (8#$mode & 0022) == 0 )) || return 1
    [[ "$current" == "/" ]] && break
    current="$(dirname -- "$current")"
  done
}

resolved_app_dir="$(readlink -f -- "$APP_DIR" 2>/dev/null || true)"
resolved_deploy_root="$(readlink -f -- "$DEPLOY_ROOT" 2>/dev/null || true)"
resolved_private_dir="$(readlink -f -- "$PRIVATE_DIR" 2>/dev/null || true)"
resolved_runtime_compose="$(readlink -f -- "$RUNTIME_COMPOSE" 2>/dev/null || true)"
[[ "$resolved_app_dir" == "$APP_DIR" && -d "$APP_DIR" && ! -L "$APP_DIR" ]] || fail_closed "app_dir_untrusted"
[[ "$resolved_deploy_root" == "$DEPLOY_ROOT" && -d "$DEPLOY_ROOT" && ! -L "$DEPLOY_ROOT" ]] || fail_closed "deploy_root_untrusted"
[[ "$resolved_private_dir" == "$PRIVATE_DIR" && -d "$PRIVATE_DIR" && ! -L "$PRIVATE_DIR" ]] || fail_closed "private_dir_untrusted"
[[ "$resolved_runtime_compose" == "$RUNTIME_COMPOSE" && -f "$RUNTIME_COMPOSE" && ! -L "$RUNTIME_COMPOSE" ]] || fail_closed "runtime_compose_untrusted"

[[ -f "$MANAGED_ENV" && ! -L "$MANAGED_ENV" ]] || fail_closed "managed_env_untrusted"
private_metadata="$(stat -c '%u %a' -- "$MANAGED_ENV" 2>/dev/null || true)"
read -r private_owner private_mode <<<"$private_metadata"
[[ "$private_owner" == "0" && "$private_mode" == "600" ]] || fail_closed "managed_env_permissions_untrusted"

[[ -n "${GITHUB_WORKSPACE:-}" ]] || fail_closed "github_workspace_missing"
resolved_workspace="$(readlink -f -- "$GITHUB_WORKSPACE" 2>/dev/null || true)"
[[ -n "$resolved_workspace" && -d "$resolved_workspace" && ! -L "$resolved_workspace" ]] || fail_closed "github_workspace_untrusted"
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || fail_closed "github_sha_invalid"
candidate_sha="$(git -C "$resolved_workspace" rev-parse --verify HEAD 2>/dev/null || true)"
[[ "$candidate_sha" == "$GITHUB_SHA" ]] || fail_closed "candidate_sha_mismatch"

live_manifest=""
live_release_sha=""
live_release_dir=""
live_release_compose=""
best_manifest_mtime="-1"
shopt -s nullglob
for manifest in "$RELEASE_ROOT"/github-*/JIEJING_GITHUB_ACTION_DEPLOY_MANIFEST.txt; do
  [[ -f "$manifest" && ! -L "$manifest" ]] || continue
  manifest_sha="$(sed -n 's/^SHA=//p' "$manifest")"
  manifest_dry_run="$(sed -n 's/^DRY_RUN=//p' "$manifest")"
  [[ "$manifest_sha" =~ ^[0-9a-f]{40}$ ]] || continue
  [[ "$manifest_dry_run" == "0" ]] || continue
  manifest_mtime="$(stat -c '%Y' -- "$manifest" 2>/dev/null || true)"
  [[ "$manifest_mtime" =~ ^[0-9]+$ ]] || continue
  if (( manifest_mtime > best_manifest_mtime )); then
    best_manifest_mtime="$manifest_mtime"
    live_manifest="$manifest"
    live_release_sha="$manifest_sha"
  fi
done
shopt -u nullglob
[[ -n "$live_manifest" ]] || fail_closed "applied_release_manifest_missing"
[[ "$live_release_sha" == "$GITHUB_SHA" ]] || fail_closed "live_release_sha_mismatch"
live_release_dir="$(dirname -- "$live_manifest")"
live_release_compose="$live_release_dir/deploy/docker-compose.public-https-staging.yml"
[[ -f "$live_release_compose" && ! -L "$live_release_compose" ]] || fail_closed "live_release_compose_missing"
cmp -s -- "$RUNTIME_COMPOSE" "$live_release_compose" || fail_closed "runtime_release_compose_mismatch"

mapfile -t api_containers < <(
  sudo -n docker ps \
    --filter 'label=com.docker.compose.project=deploy' \
    --filter 'label=com.docker.compose.service=jiejing-saas' \
    --format '{{.ID}}'
)
[[ "${#api_containers[@]}" -eq 1 ]] || fail_closed "runtime_api_container_not_unique"
api_container_id="${api_containers[0]}"
runtime_project="$(sudo -n docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$api_container_id" 2>/dev/null || true)"
runtime_service="$(sudo -n docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$api_container_id" 2>/dev/null || true)"
runtime_config_files="$(sudo -n docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$api_container_id" 2>/dev/null || true)"
runtime_project_dir="$(sudo -n docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$api_container_id" 2>/dev/null || true)"
runtime_image="$(sudo -n docker inspect --format '{{.Config.Image}}' "$api_container_id" 2>/dev/null || true)"
runtime_working_dir="$(sudo -n docker inspect --format '{{.Config.WorkingDir}}' "$api_container_id" 2>/dev/null || true)"
[[ "$runtime_project" == "deploy" ]] || fail_closed "runtime_project_mismatch"
[[ "$runtime_service" == "jiejing-saas" ]] || fail_closed "runtime_service_mismatch"
[[ "$runtime_config_files" == "$RUNTIME_COMPOSE" ]] || fail_closed "runtime_config_files_mismatch"
[[ "$runtime_project_dir" == "$APP_DIR/deploy" ]] || fail_closed "runtime_project_dir_mismatch"
[[ -n "$runtime_image" ]] || fail_closed "runtime_image_missing"
[[ "$runtime_working_dir" == "/app" ]] || fail_closed "runtime_working_dir_mismatch"

trusted_root_owned_path_chain_is_safe "$TRUSTED_RUNTIME_ENV_GUARD" || fail_closed "runtime_env_guard_untrusted"
sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check \
  --compose "$RUNTIME_COMPOSE" \
  --managed-env "$MANAGED_ENV" \
  --secret-env "$OAUTH_ENV_PATH" \
  --postgres-env "$POSTGRES_ENV" \
  --required-runtime-service jiejing-saas \
  --required-runtime-service jiejing-worker \
  >/dev/null 2>&1 || fail_closed "runtime_env_guard_blocked"

echo "LIVE_RELEASE_GUARD_STATUS=ready"
sudo -n docker run --rm -w /app "$runtime_image" python -c \
  "import importlib.util,sys; from pathlib import Path; ok=importlib.util.find_spec('tencentcloud') is not None and Path('tools/jiejing_configure_tencent_runtime_env.py').is_file(); sys.exit(0 if ok else 2)" \
  >/dev/null 2>&1 || fail_closed "runtime_probe_dependency_missing"

probe_output="$(sudo -n docker run --rm --network bridge \
  --mount "type=bind,src=$PRIVATE_DIR,dst=/private" \
  -w /app "$runtime_image" python tools/jiejing_configure_tencent_runtime_env.py \
  --env-file /private/tencent-managed.env \
  --verify-provider-cls-probe --apply \
  2>/dev/null)" || fail_closed "provider_cls_probe_failed"

probe_result="$(python3 -c '
import json
import sys

payload = json.load(sys.stdin)
verified = (
    payload.get("status") == "verified"
    and payload.get("probe_uploaded") is True
    and payload.get("probe_searchable") is True
    and payload.get("alarm_queries_exclude_probe") is True
    and payload.get("event_field_count") == 12
    and payload.get("event_allowlist_exact") is True
    and payload.get("notification_test_sent") is False
    and payload.get("resource_ids_exposed") is False
    and payload.get("secret_exposed") is False
    and payload.get("verification_evidence_recorded") is True
)
print("verified" if verified else "blocked")
sys.exit(0 if verified else 2)
' <<<"$probe_output" 2>/dev/null)" || {
  unset probe_output
  fail_closed "provider_cls_probe_contract_rejected"
}
unset probe_output
[[ "$probe_result" == "verified" ]] || fail_closed "provider_cls_probe_not_verified"
echo "CLS_PROBE_STATUS=verified"

COMPOSE_ARGS=(-p deploy -f "$RUNTIME_COMPOSE")

wait_for_api_container_health() {
  local container_id state health_status
  local attempt
  for attempt in $(seq 1 45); do
    container_id="$(sudo -n docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-saas 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      state="$(sudo -n docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
      health_status="$(sudo -n docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"
      if [[ "$state" == "running" && "$health_status" == "healthy" ]]; then
        return 0
      fi
      if [[ "$state" == "running" && "$health_status" == "none" ]] \
        && health_contract_ready 'http://127.0.0.1:18080/health'; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

health_contract_ready() {
  local url="$1"
  local payload_json
  payload_json="$(curl -fsS --max-time 12 -A 'Mozilla/5.0 Jiejing-CLS-Probe-Maintenance' "$url" 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
ready = (
    payload.get("status") == "ok"
    and payload.get("database_startup_status") == "ready"
    and payload.get("real_platform_writes_enabled") is False
    and payload.get("requested_real_platform_writes") is False
    and payload.get("secret_exposed") is False
)
sys.exit(0 if ready else 2)
' <<<"$payload_json" >/dev/null 2>&1
}

deep_contract_ready() {
  local payload_json
  payload_json="$(curl -fsS --max-time 12 -A 'Mozilla/5.0 Jiejing-CLS-Probe-Maintenance' \
    'https://app.jiejing.shop/health/deep' 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
operational = payload.get("operational_health") or {}
ready = (
    operational.get("status") == "ready"
    and operational.get("database", {}).get("status") == "ready"
    and operational.get("queue", {}).get("status") == "ready"
    and operational.get("worker", {}).get("status") == "ready"
    and operational.get("secret_exposed") is False
)
sys.exit(0 if ready else 2)
' <<<"$payload_json" >/dev/null 2>&1
}

readiness_contract_ready() {
  local payload_json
  payload_json="$(curl -fsS --max-time 18 -A 'Mozilla/5.0 Jiejing-CLS-Probe-Maintenance' \
    'https://app.jiejing.shop/readiness/product-saas' 2>/dev/null)" || return 1
  python3 tools/jiejing_cls_public_readiness_contract.py \
    <<<"$payload_json" >/dev/null 2>&1
}

sudo -n docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-saas \
  >/dev/null 2>&1 || fail_closed "api_recreate_failed"
wait_for_api_container_health || fail_closed "api_container_unhealthy"
health_contract_ready 'http://127.0.0.1:18080/health' || fail_closed "local_api_health_failed"
health_contract_ready 'https://app.jiejing.shop/health' || fail_closed "public_api_health_failed"
deep_contract_ready || fail_closed "public_deep_health_failed_before_worker"
echo "API_RELOAD_STATUS=ready"

sudo -n docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-worker \
  >/dev/null 2>&1 || fail_closed "worker_recreate_failed"

worker_ready="false"
for attempt in $(seq 1 45); do
  worker_container_id="$(sudo -n docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-worker 2>/dev/null || true)"
  worker_state=""
  if [[ -n "$worker_container_id" ]]; then
    worker_state="$(sudo -n docker inspect --format '{{.State.Status}}' "$worker_container_id" 2>/dev/null || true)"
  fi
  if [[ "$worker_state" == "running" ]] && deep_contract_ready; then
    worker_ready="true"
    break
  fi
  sleep 2
done
[[ "$worker_ready" == "true" ]] || fail_closed "worker_runtime_unhealthy"
echo "WORKER_RELOAD_STATUS=ready"

readiness_contract_ready || fail_closed "public_readiness_contract_failed"
echo "READINESS_STATUS=verified"
echo "JIEJING_CLS_PROBE_AUTO_REFRESH_STATUS=success"
