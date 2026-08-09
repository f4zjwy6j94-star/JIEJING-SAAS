#!/usr/bin/env bash
set -euo pipefail

# Read-only readiness check for the Tencent Cloud GitHub self-hosted runner.
# It does not deploy, restart services, delete files, or print environment
# variables. It only reports whether the runner host is ready for dry-run/apply.

APP_DIR="${JIEJING_STAGING_APP_DIR:-/opt/jiejing-staging/app}"
DEPLOY_ROOT="${JIEJING_STAGING_DEPLOY_ROOT:-/opt/jiejing-staging}"
BACKUP_ROOT="${JIEJING_STAGING_BACKUP_ROOT:-$DEPLOY_ROOT/github-action-backups}"
RELEASE_ROOT="${JIEJING_STAGING_RELEASE_ROOT:-$DEPLOY_ROOT/github-action-releases}"
HEALTH_URL="${JIEJING_RUNNER_DOCTOR_HEALTH_URL:-http://127.0.0.1:8788/health}"
PUBLIC_HEALTH_URL="${JIEJING_RUNNER_DOCTOR_PUBLIC_HEALTH_URL:-https://app.jiejing.shop/health}"
DISK_WARN_PERCENT="${JIEJING_RUNNER_DOCTOR_DISK_WARN_PERCENT:-90}"
DISK_BLOCK_PERCENT="${JIEJING_RUNNER_DOCTOR_DISK_BLOCK_PERCENT:-95}"
TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"

blockers=()
warnings=()

add_blocker() {
  blockers+=("$1")
}

add_warning() {
  warnings+=("$1")
}

print_list() {
  local prefix="$1"
  shift || true
  if (($# == 0)); then
    echo "${prefix}=none"
    return
  fi
  local joined=""
  local item
  for item in "$@"; do
    if [[ -n "$joined" ]]; then
      joined="${joined},${item}"
    else
      joined="$item"
    fi
  done
  echo "${prefix}=${joined}"
}

resolved_app_dir="$(readlink -f -- "$APP_DIR" 2>/dev/null || true)"
resolved_deploy_root="$(readlink -f -- "$DEPLOY_ROOT" 2>/dev/null || true)"
app_dir_safe="false"
deploy_root_safe="false"

if [[ -z "$resolved_deploy_root" ]]; then
  add_blocker "deploy_root_missing"
else
  case "$resolved_deploy_root" in
    /opt/jiejing-staging|/opt/jiejing-staging/*) deploy_root_safe="true" ;;
    *) add_blocker "deploy_root_outside_staging" ;;
  esac
fi

if [[ -z "$resolved_app_dir" || ! -d "$resolved_app_dir" ]]; then
  add_blocker "app_dir_missing"
else
  case "$resolved_app_dir" in
    /opt/jiejing-staging/app|/opt/jiejing-staging/app/*) app_dir_safe="true" ;;
    *) add_blocker "app_dir_outside_staging" ;;
  esac
  if [[ "$app_dir_safe" == "true" ]]; then
    [[ -f "$resolved_app_dir/app.js" ]] || add_blocker "app_js_missing"
    [[ -f "$resolved_app_dir/deploy/apply-staging-patch.sh" ]] || add_blocker "apply_staging_patch_missing"
    [[ -f "$resolved_app_dir/deploy/docker-compose.public-https-staging.yml" || -f "$resolved_app_dir/deploy/docker-compose.public-staging.yml" ]] || add_blocker "staging_compose_missing"
  fi
fi

if [[ -n "${GITHUB_WORKSPACE:-}" ]]; then
  [[ -f "$GITHUB_WORKSPACE/app.js" ]] || add_blocker "github_workspace_app_js_missing"
  [[ -f "$GITHUB_WORKSPACE/deploy/github-actions/jiejing-staging-deploy.sh" ]] || add_blocker "github_workspace_deploy_script_missing"
else
  add_warning "not_running_inside_github_actions"
fi

command -v docker >/dev/null 2>&1 || add_blocker "docker_cli_missing"
if command -v docker >/dev/null 2>&1; then
  docker compose version >/dev/null 2>&1 || add_blocker "docker_compose_missing_or_unavailable"
fi

command -v rsync >/dev/null 2>&1 || add_blocker "rsync_missing"
command -v curl >/dev/null 2>&1 || add_warning "curl_missing"

if sudo -n true >/dev/null 2>&1; then
  echo "SUDO_NONINTERACTIVE=ready"
else
  echo "SUDO_NONINTERACTIVE=blocked"
  add_blocker "sudo_noninteractive_unavailable"
fi

runtime_guard_status="blocked"
private_dir="$resolved_deploy_root/private"
runtime_compose="$resolved_app_dir/deploy/docker-compose.public-https-staging.yml"
if [[ ! -f "$runtime_compose" ]]; then
  runtime_compose="$resolved_app_dir/deploy/docker-compose.public-staging.yml"
fi
candidate_workspace="${GITHUB_WORKSPACE:-}"
resolved_candidate_workspace="$(readlink -f -- "$candidate_workspace" 2>/dev/null || true)"
candidate_compose="$resolved_candidate_workspace/deploy/docker-compose.public-https-staging.yml"
candidate_sha="${GITHUB_SHA:-}"
live_release_sha=""
cost_saver_override=""

trusted_root_owned_path_chain_is_safe() {
  local path="$1"
  local resolved current metadata owner mode
  case "$path" in
    /*) ;;
    *) return 1 ;;
  esac
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

runtime_compose_is_safe() {
  local resolved
  [[ -f "$runtime_compose" && ! -L "$runtime_compose" ]] || return 1
  resolved="$(readlink -f -- "$runtime_compose" 2>/dev/null || true)"
  [[ "$resolved" == "$runtime_compose" ]]
}

candidate_compose_is_safe() {
  local resolved_candidate tracked_path working_blob head_blob
  [[ -n "$candidate_workspace" && ! -L "$candidate_workspace" ]] || return 1
  [[ -n "$resolved_candidate_workspace" && -d "$resolved_candidate_workspace" && \
    ! -L "$resolved_candidate_workspace" ]] || return 1
  [[ -f "$candidate_compose" && ! -L "$candidate_compose" ]] || return 1
  resolved_candidate="$(readlink -f -- "$candidate_compose" 2>/dev/null || true)"
  [[ -n "$resolved_candidate" && "$resolved_candidate" == "$candidate_compose" ]] || return 1
  case "$resolved_candidate" in
    "$resolved_candidate_workspace"/*) ;;
    *) return 1 ;;
  esac
  tracked_path="deploy/docker-compose.public-https-staging.yml"
  git -C "$resolved_candidate_workspace" ls-files --error-unmatch -- "$tracked_path" >/dev/null 2>&1 || return 1
  git -C "$resolved_candidate_workspace" diff --quiet --exit-code -- "$tracked_path" || return 1
  git -C "$resolved_candidate_workspace" diff --cached --quiet --exit-code -- "$tracked_path" || return 1
  working_blob="$(git -C "$resolved_candidate_workspace" hash-object -- "$candidate_compose" 2>/dev/null || true)"
  head_blob="$(git -C "$resolved_candidate_workspace" rev-parse "HEAD:$tracked_path" 2>/dev/null || true)"
  [[ -n "$working_blob" && "$working_blob" == "$head_blob" ]]
}

candidate_checkout_sha_is_exact() {
  local checkout_sha
  [[ "$candidate_sha" =~ ^[0-9a-f]{40}$ ]] || return 1
  checkout_sha="$(git -C "$resolved_candidate_workspace" rev-parse --verify HEAD 2>/dev/null || true)"
  [[ "$checkout_sha" == "$candidate_sha" ]]
}

live_release_sha_is_verified() {
  local manifest resolved_manifest release_dir release_compose backup_dir
  local run_id run_attempt release_sha stamp dry_run mtime best_mtime="-1"
  local best_sha=""
  shopt -s nullglob
  for manifest in "$RELEASE_ROOT"/github-*/JIEJING_GITHUB_ACTION_DEPLOY_MANIFEST.txt; do
    [[ -f "$manifest" && ! -L "$manifest" ]] || continue
    resolved_manifest="$(readlink -f -- "$manifest" 2>/dev/null || true)"
    case "$resolved_manifest" in
      "$resolved_deploy_root"/github-action-releases/*/JIEJING_GITHUB_ACTION_DEPLOY_MANIFEST.txt) ;;
      *) continue ;;
    esac
    run_id="$(sed -n 's/^RUN_ID=//p' "$manifest")"
    run_attempt="$(sed -n 's/^RUN_ATTEMPT=//p' "$manifest")"
    release_sha="$(sed -n 's/^SHA=//p' "$manifest")"
    stamp="$(sed -n 's/^STAMP=//p' "$manifest")"
    dry_run="$(sed -n 's/^DRY_RUN=//p' "$manifest")"
    [[ "$run_id" =~ ^[0-9]+$ && "$run_attempt" =~ ^[0-9]+$ && \
      "$release_sha" =~ ^[0-9a-f]{40}$ && "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ && \
      "$dry_run" == "0" ]] || continue
    release_dir="$(dirname -- "$manifest")"
    release_compose="$release_dir/deploy/docker-compose.public-https-staging.yml"
    backup_dir="$BACKUP_ROOT/pre-github-${run_id}-${run_attempt}-${stamp}"
    [[ -d "$backup_dir" && ! -L "$backup_dir" && -f "$release_compose" && \
      ! -L "$release_compose" && -f "$release_dir/app.js" ]] || continue
    cmp -s -- "$runtime_compose" "$release_compose" || continue
    cmp -s -- "$resolved_app_dir/app.js" "$release_dir/app.js" || continue
    mtime="$(stat -c '%Y' -- "$manifest" 2>/dev/null || true)"
    [[ "$mtime" =~ ^[0-9]+$ ]] || continue
    if (( mtime > best_mtime )); then
      best_mtime="$mtime"
      best_sha="$release_sha"
    fi
  done
  shopt -u nullglob
  [[ -n "$best_sha" && "$best_sha" != "$candidate_sha" ]] || return 1
  live_release_sha="$best_sha"
}

override_args=()
if [[ "$app_dir_safe" != "true" || "$deploy_root_safe" != "true" ]]; then
  :
elif [[ ! -f "$TRUSTED_RUNTIME_ENV_GUARD" ]]; then
  add_blocker "runtime_env_guard_missing"
elif ! trusted_root_owned_path_chain_is_safe "$TRUSTED_RUNTIME_ENV_GUARD"; then
  add_blocker "runtime_env_guard_untrusted"
elif ! runtime_compose_is_safe; then
  add_blocker "runtime_env_compose_missing"
elif ! candidate_compose_is_safe; then
  add_blocker "runtime_env_candidate_compose_untrusted"
elif ! candidate_checkout_sha_is_exact; then
  add_blocker "runtime_env_candidate_checkout_unverified"
elif [[ "${JIEJING_USE_COST_SAVER_OVERRIDE:-false}" == "true" ]]; then
  cost_saver_override="${JIEJING_COST_SAVER_COMPOSE_OVERRIDE:-$private_dir/docker-compose.cost-saver-local.yml}"
  if [[ "$cost_saver_override" != "$private_dir/docker-compose.cost-saver-local.yml" ]] || \
    ! trusted_root_owned_path_chain_is_safe "$cost_saver_override"; then
    add_blocker "runtime_env_cost_saver_override_untrusted"
  else
    override_args+=(--compose-override "$cost_saver_override")
  fi
fi

if [[ "$app_dir_safe" == "true" && "$deploy_root_safe" == "true" && \
  -f "$TRUSTED_RUNTIME_ENV_GUARD" ]] && trusted_root_owned_path_chain_is_safe "$TRUSTED_RUNTIME_ENV_GUARD" && \
  runtime_compose_is_safe && candidate_compose_is_safe && candidate_checkout_sha_is_exact && \
  [[ "${#override_args[@]}" -gt 0 || "${JIEJING_USE_COST_SAVER_OVERRIDE:-false}" != "true" ]]; then
  if ! sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check \
    --compose "$candidate_compose" \
    --compose-runtime-path "$runtime_compose" \
    --managed-env "$private_dir/tencent-managed.env" \
    --secret-env "$private_dir/jiejing-saas.staging-oauth.env" \
    --postgres-env "$private_dir/postgres-localqueue.env" \
    --required-runtime-service jiejing-saas \
    --required-runtime-service jiejing-worker \
    "${override_args[@]}" \
    >/dev/null 2>/dev/null; then
    add_blocker "runtime_env_candidate_guard_blocked"
  elif sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check \
    --compose "$runtime_compose" \
    --managed-env "$private_dir/tencent-managed.env" \
    --secret-env "$private_dir/jiejing-saas.staging-oauth.env" \
    --postgres-env "$private_dir/postgres-localqueue.env" \
    --required-runtime-service jiejing-saas \
    --required-runtime-service jiejing-worker \
    "${override_args[@]}" \
    >/dev/null 2>/dev/null; then
    runtime_guard_status="ready"
  elif live_release_sha_is_verified && \
    git -C "$resolved_candidate_workspace" merge-base --is-ancestor "$live_release_sha" "$candidate_sha"; then
    runtime_guard_status="ready_transition"
    add_warning "runtime_env_live_compose_transition_detected"
  else
    add_blocker "runtime_env_live_transition_unverified"
  fi
fi
echo "RUNTIME_ENV_GUARD_STATUS=$runtime_guard_status"

if [[ -n "$resolved_deploy_root" ]]; then
  [[ -w "$resolved_deploy_root" ]] || add_blocker "deploy_root_not_writable_by_runner"
  backup_parent="$(dirname "$BACKUP_ROOT")"
  release_parent="$(dirname "$RELEASE_ROOT")"
  [[ -d "$backup_parent" && -w "$backup_parent" ]] || add_blocker "backup_parent_not_writable_by_runner"
  [[ -d "$release_parent" && -w "$release_parent" ]] || add_blocker "release_parent_not_writable_by_runner"

  disk_percent="$(df -P "$resolved_deploy_root" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
  if [[ "$disk_percent" =~ ^[0-9]+$ ]]; then
    echo "DISK_USED_PERCENT=$disk_percent"
    if (( disk_percent >= DISK_BLOCK_PERCENT )); then
      add_blocker "disk_usage_at_or_above_${DISK_BLOCK_PERCENT}_percent"
    elif (( disk_percent >= DISK_WARN_PERCENT )); then
      add_warning "disk_usage_at_or_above_${DISK_WARN_PERCENT}_percent"
    fi
  else
    add_warning "disk_usage_unknown"
  fi
fi

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 8 "$HEALTH_URL" >/tmp/jiejing-runner-doctor-health.json 2>/tmp/jiejing-runner-doctor-health.err; then
    echo "LOCAL_HEALTH=ready"
  else
    echo "LOCAL_HEALTH=blocked"
    add_warning "local_health_unreachable"
  fi

  if [[ -n "$PUBLIC_HEALTH_URL" ]]; then
    if curl -fsS --max-time 12 "$PUBLIC_HEALTH_URL" >/tmp/jiejing-runner-doctor-public-health.json 2>/tmp/jiejing-runner-doctor-public-health.err; then
      echo "PUBLIC_HEALTH=ready"
    else
      echo "PUBLIC_HEALTH=blocked"
      add_warning "public_health_unreachable"
    fi
  fi
fi

if ((${#blockers[@]} == 0)); then
  status="ready"
else
  status="blocked"
fi

echo "JIEJING_RUNNER_DOCTOR_STATUS=$status"
print_list "JIEJING_RUNNER_DOCTOR_BLOCKERS" "${blockers[@]}"
print_list "JIEJING_RUNNER_DOCTOR_WARNINGS" "${warnings[@]}"
echo "SECRET_EXPOSED=false"

if [[ "$status" == "ready" ]]; then
  exit 0
fi
exit 2
