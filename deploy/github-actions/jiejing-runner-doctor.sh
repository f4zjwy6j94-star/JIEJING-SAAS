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
DISK_WARN_PERCENT="${JIEJING_RUNNER_DOCTOR_DISK_WARN_PERCENT:-90}"
DISK_BLOCK_PERCENT="${JIEJING_RUNNER_DOCTOR_DISK_BLOCK_PERCENT:-95}"

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

if [[ -z "$resolved_deploy_root" ]]; then
  add_blocker "deploy_root_missing"
else
  case "$resolved_deploy_root" in
    /opt/jiejing-staging|/opt/jiejing-staging/*) ;;
    *) add_blocker "deploy_root_outside_staging" ;;
  esac
fi

if [[ -z "$resolved_app_dir" ]]; then
  add_blocker "app_dir_missing"
else
  case "$resolved_app_dir" in
    /opt/jiejing-staging/app|/opt/jiejing-staging/app/*) ;;
    *) add_blocker "app_dir_outside_staging" ;;
  esac
  [[ -f "$resolved_app_dir/app.js" ]] || add_blocker "app_js_missing"
  [[ -f "$resolved_app_dir/deploy/apply-staging-patch.sh" ]] || add_blocker "apply_staging_patch_missing"
  [[ -f "$resolved_app_dir/deploy/docker-compose.public-https-staging.yml" || -f "$resolved_app_dir/deploy/docker-compose.public-staging.yml" ]] || add_blocker "staging_compose_missing"
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
