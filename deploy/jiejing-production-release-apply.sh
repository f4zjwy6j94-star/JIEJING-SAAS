#!/usr/bin/env bash
set -euo pipefail

# Atomic, confirmation-gated production release application. The uploaded
# bundle contains code only. Existing server-private env and Vault token files
# are reused in place and are never copied into the candidate release.

EXPECTED_CONFIRM="deploy app.jiejing.shop production"
PRODUCTION_ROOT="/opt/jiejing-production"
ACTIVE_LINK="$PRODUCTION_ROOT/app"
RELEASE_ROOT="$PRODUCTION_ROOT/releases"
PATCH_DIR="${1:-}"
BUNDLE_SHA256="${2:-}"
MANIFEST_SHA256="${3:-}"
SOURCE_SHA="${4:-}"
CONFIRM="${JIEJING_PRODUCTION_DEPLOY_CONFIRM:-}"
DRY_RUN="${JIEJING_PRODUCTION_DEPLOY_DRY_RUN:-1}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PUBLIC_URL="https://app.jiejing.shop"
DEPLOY_LOCK="/run/lock/jiejing-production-deploy.lock"
MAINTENANCE_LOCK="/run/lock/jiejing-production-maintenance.lock"
EVIDENCE_REFRESH_WRAPPER="/usr/local/libexec/jiejing/jiejing-production-evidence-auto-refresh.sh"
EVIDENCE_REFRESH_SERVICE_PATH="/etc/systemd/system/jiejing-production-evidence-refresh.service"
EVIDENCE_REFRESH_TIMER_PATH="/etc/systemd/system/jiejing-production-evidence-refresh.timer"
EVIDENCE_REFRESH_SERVICE="jiejing-production-evidence-refresh.service"
EVIDENCE_REFRESH_TIMER="jiejing-production-evidence-refresh.timer"
mutation_started=0
current_stage="preflight"
deploy_lock_held=0
maintenance_lock_held=0
unit_transaction_active=0
unit_transaction_failure_in_progress=0
dry_run_candidate=""
dry_run_cleanup_active=0

refuse() {
  printf '%s\n' "$1" >&2
  exit "${2:-1}"
}

validate_evidence_refresh_candidate() {
  local candidate_root="$1"
  local wrapper="$candidate_root/deploy/jiejing-production-evidence-auto-refresh.sh"
  local service="$candidate_root/deploy/systemd/jiejing-production-evidence-refresh.service"
  local timer="$candidate_root/deploy/systemd/jiejing-production-evidence-refresh.timer"

  [[ -f "$wrapper" && ! -L "$wrapper" ]] || refuse "REFUSE_EVIDENCE_REFRESH_WRAPPER_MISSING=1" 31
  [[ -f "$service" && ! -L "$service" ]] || refuse "REFUSE_EVIDENCE_REFRESH_SERVICE_MISSING=1" 31
  [[ -f "$timer" && ! -L "$timer" ]] || refuse "REFUSE_EVIDENCE_REFRESH_TIMER_MISSING=1" 31
  bash -n "$wrapper" || refuse "REFUSE_EVIDENCE_REFRESH_WRAPPER_SYNTAX=1" 31
  python3 - "$service" "$timer" <<'PY' || refuse "REFUSE_EVIDENCE_REFRESH_UNIT_CONTRACT=1" 31
from pathlib import Path
import sys

expected_service = """[Unit]
Description=Jiejing production reliability evidence refresh
Requires=docker.service
Wants=network-online.target
After=docker.service network-online.target

[Service]
Type=oneshot
User=root
Group=root
UMask=0077
ExecStart=/usr/local/libexec/jiejing/jiejing-production-evidence-auto-refresh.sh
TimeoutStartSec=20min
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/opt/jiejing-production /run/lock
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
StandardOutput=journal
StandardError=journal
SyslogIdentifier=jiejing-production-evidence-refresh
""".splitlines()
expected_timer = """[Unit]
Description=Schedule Jiejing production reliability evidence refresh

[Timer]
OnCalendar=*-*-* 00,12:17:00
RandomizedDelaySec=9m
Persistent=true
AccuracySec=1m
Unit=jiejing-production-evidence-refresh.service

[Install]
WantedBy=timers.target
""".splitlines()
service = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
timer = Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
raise SystemExit(0 if service == expected_service and timer == expected_timer else 1)
PY
}

require_flock() {
  command -v flock >/dev/null 2>&1 || refuse "REFUSE_FLOCK_UNAVAILABLE=1" 32
}

acquire_deploy_lock() {
  local flock_rc
  require_flock
  if ! exec 8>"$DEPLOY_LOCK"; then
    refuse "REFUSE_LOCK_OPEN_FAILED=deploy" 33
  fi
  if flock -n 8; then
    deploy_lock_held=1
    return 0
  else
    flock_rc=$?
  fi
  if [[ "$flock_rc" == "1" ]]; then
    refuse "REFUSE_PRODUCTION_DEPLOY_LOCK_BUSY=1" 34
  fi
  refuse "REFUSE_LOCK_ACQUIRE_FAILED=deploy:$flock_rc" 35
}

acquire_maintenance_lock() {
  local flock_rc
  require_flock
  if ! exec 9>"$MAINTENANCE_LOCK"; then
    refuse "REFUSE_LOCK_OPEN_FAILED=maintenance" 36
  fi
  if flock -n 9; then
    maintenance_lock_held=1
    return 0
  else
    flock_rc=$?
  fi
  if [[ "$flock_rc" == "1" ]]; then
    refuse "REFUSE_PRODUCTION_MAINTENANCE_LOCK_BUSY=1" 37
  fi
  refuse "REFUSE_LOCK_ACQUIRE_FAILED=maintenance:$flock_rc" 38
}

release_maintenance_lock() {
  if [[ "$maintenance_lock_held" == "1" ]]; then
    flock -u 9 || true
    exec 9>&-
    maintenance_lock_held=0
  fi
}

release_deploy_lock() {
  if [[ "$deploy_lock_held" == "1" ]]; then
    flock -u 8 || true
    exec 8>&-
    deploy_lock_held=0
  fi
}

create_dry_run_candidate() {
  local resolved metadata owner mode
  dry_run_candidate="$(mktemp -d --tmpdir=/tmp 'jiejing-production-dry-run-XXXXXXXX.d')" || {
    dry_run_candidate=""
    release_dir=""
    return 1
  }
  release_dir="$dry_run_candidate"
  case "$dry_run_candidate" in
    /tmp/jiejing-production-dry-run-????????.d) ;;
    *) return 1 ;;
  esac
  resolved="$(readlink -f -- "$dry_run_candidate" 2>/dev/null || true)"
  case "$resolved" in
    /tmp/jiejing-production-dry-run-????????.d) ;;
    *) return 1 ;;
  esac
  [[ "$dry_run_candidate" == "$resolved" && -d "$resolved" && ! -L "$resolved" ]] \
    || return 1
  metadata="$(stat -c '%u %a' -- "$resolved" 2>/dev/null || true)"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$EUID" && "$mode" == "700" ]]
}

cleanup_dry_run_candidate() {
  local candidate="$1" resolved metadata owner mode
  resolved="$(readlink -f -- "$candidate" 2>/dev/null || true)"
  case "$resolved" in
    /tmp/jiejing-production-dry-run-????????.d) ;;
    *) printf '%s\n' "REFUSE_DRY_RUN_CANDIDATE_UNTRUSTED=1" >&2; return 1 ;;
  esac
  [[ "$candidate" == "$resolved" && -d "$resolved" && ! -L "$resolved" ]] \
    || { printf '%s\n' "REFUSE_DRY_RUN_CANDIDATE_UNTRUSTED=1" >&2; return 1; }
  metadata="$(stat -c '%u %a' -- "$resolved" 2>/dev/null || true)"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$EUID" && "$mode" =~ ^[0-7]{3,4}$ ]] \
    || { printf '%s\n' "REFUSE_DRY_RUN_CANDIDATE_UNTRUSTED=1" >&2; return 1; }
  (( (8#$mode & 0022) == 0 )) \
    || { printf '%s\n' "REFUSE_DRY_RUN_CANDIDATE_UNTRUSTED=1" >&2; return 1; }
  rm -rf --one-file-system -- "$resolved" || return 1
  [[ ! -e "$resolved" && ! -L "$resolved" ]]
}

dry_run_cleanup_handler() {
  trap '' HUP INT TERM
  trap - EXIT
  local exit_code="${1:-1}"
  if [[ "$dry_run_cleanup_active" == "1" && -n "$dry_run_candidate" ]]; then
    cleanup_dry_run_candidate "$dry_run_candidate" || exit_code=39
  fi
  dry_run_cleanup_active=0
  dry_run_candidate=""
  release_dir=""
  trap - HUP INT TERM
  exit "$exit_code"
}

arm_dry_run_cleanup_traps() {
  dry_run_cleanup_active=1
  trap 'dry_run_cleanup_handler 129' HUP
  trap 'dry_run_cleanup_handler 130' INT
  trap 'dry_run_cleanup_handler 143' TERM
  trap 'dry_run_cleanup_handler "$?"' EXIT
}

[[ "$CONFIRM" == "$EXPECTED_CONFIRM" ]] || refuse "REFUSE_PRODUCTION_CONFIRMATION_MISMATCH=1" 12
[[ "$DRY_RUN" == "0" || "$DRY_RUN" == "1" ]] || refuse "REFUSE_INVALID_PRODUCTION_DRY_RUN=$DRY_RUN" 13
[[ "$BUNDLE_SHA256" =~ ^[0-9a-f]{64}$ ]] || refuse "REFUSE_INVALID_BUNDLE_SHA256=1" 14
[[ "$MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]] || refuse "REFUSE_INVALID_MANIFEST_SHA256=1" 15
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || refuse "REFUSE_INVALID_SOURCE_SHA=1" 16
[[ -d "$PATCH_DIR" && ! -L "$PATCH_DIR" ]] || refuse "REFUSE_INVALID_PATCH_DIR=1" 17

resolved_patch_dir="$(readlink -f -- "$PATCH_DIR" 2>/dev/null || true)"
case "$resolved_patch_dir" in
  /tmp/jiejing-production-*.d) ;;
  *) refuse "REFUSE_PATCH_DIR_OUTSIDE_TMP=$resolved_patch_dir" 18 ;;
esac
[[ -f "$resolved_patch_dir/app.js" ]] || refuse "REFUSE_PATCH_APP_MISSING=1" 19
[[ -f "$resolved_patch_dir/Dockerfile.saas" ]] || refuse "REFUSE_PATCH_DOCKERFILE_MISSING=1" 20
[[ -f "$resolved_patch_dir/deploy/docker-compose.production-pilot.yml" ]] || refuse "REFUSE_PATCH_COMPOSE_MISSING=1" 21
if find "$resolved_patch_dir" -type l -print -quit | grep -q .; then
  refuse "REFUSE_PATCH_SYMLINK=1" 22
fi
if find "$resolved_patch_dir" -type f \( \
  -name '.env' -o \
  \( -name '*.env' ! -name '*.env.example' \) -o \
  -name '*.pem' -o \
  -name '*.key' \
\) -print -quit | grep -q .; then
  refuse "REFUSE_PATCH_SECRET_FILE=1" 23
fi
validate_evidence_refresh_candidate "$resolved_patch_dir"

if [[ "$DRY_RUN" == "0" ]]; then
  acquire_deploy_lock
  acquire_maintenance_lock
fi

active_app="$(readlink -f -- "$ACTIVE_LINK" 2>/dev/null || true)"
case "$active_app" in
  "$RELEASE_ROOT"/*/app) ;;
  *) refuse "REFUSE_ACTIVE_RELEASE_OUTSIDE_ROOT=$active_app" 24 ;;
esac
previous_release="$(dirname -- "$active_app")"

environment_file="$(docker inspect deploy-jiejing-saas-1 --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' 2>/dev/null || true)"
private_dir="$(dirname -- "$environment_file")"
private_dir="$(readlink -f -- "$private_dir" 2>/dev/null || true)"
case "$private_dir" in
  "$PRODUCTION_ROOT/private"|"$RELEASE_ROOT"/*/private) ;;
  *) refuse "REFUSE_PRIVATE_DIR_OUTSIDE_ROOT=$private_dir" 25 ;;
esac
[[ -f "$private_dir/production-compose.env" && ! -L "$private_dir/production-compose.env" ]] || refuse "REFUSE_PRIVATE_COMPOSE_ENV_MISSING=1" 26
[[ -f "$private_dir/jiejing-saas.production.env" && ! -L "$private_dir/jiejing-saas.production.env" ]] || refuse "REFUSE_PRIVATE_APP_ENV_MISSING=1" 27
[[ -f "$private_dir/jiejing-vault-token.d/jiejing-vault-token" && ! -L "$private_dir/jiejing-vault-token.d/jiejing-vault-token" ]] || refuse "REFUSE_PRIVATE_VAULT_TOKEN_MISSING=1" 28

short_sha="${SOURCE_SHA:0:12}"
if [[ "$DRY_RUN" == "1" ]]; then
  arm_dry_run_cleanup_traps
  create_dry_run_candidate || refuse "REFUSE_DRY_RUN_CANDIDATE_CREATE_FAILED=1" 39
else
  release_dir="$RELEASE_ROOT/${STAMP}-${short_sha}"
  [[ ! -e "$release_dir" ]] || refuse "REFUSE_RELEASE_ALREADY_EXISTS=$release_dir" 29
  install -d -m 0750 -o root -g root "$release_dir"
fi
candidate_app="$release_dir/app"
install -d -m 0755 -o root -g root "$candidate_app"

rsync -a --delete \
  --exclude '.git/' \
  --exclude 'node_modules/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'output/' \
  --exclude '*.pyc' \
  --exclude '*.sqlite' \
  --exclude '*.sqlite3' \
  --exclude '*.db' \
  --exclude '.env' \
  --exclude '*.env' \
  --exclude '*.pem' \
  --exclude '*.key' \
  "$active_app/" "$candidate_app/"
rsync -a \
  --exclude '.git/' \
  --exclude 'node_modules/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'output/' \
  --exclude '*.pyc' \
  --exclude '*.sqlite' \
  --exclude '*.sqlite3' \
  --exclude '*.db' \
  --exclude '.env' \
  --exclude '*.env' \
  --exclude '*.pem' \
  --exclude '*.key' \
  "$resolved_patch_dir/" "$candidate_app/"

chown -R root:root "$release_dir"
find "$release_dir" -type d -exec chmod 0755 {} +
chmod 0750 "$release_dir"
find "$release_dir" -type f -exec chmod 0644 {} +
chmod -R go-w "$release_dir"

(
  cd "$candidate_app"
  python3 tools/jiejing_secret_scan.py
  python3 -m py_compile \
    jiejing_saas/api_server.py \
    jiejing_saas/readiness.py \
    jiejing_saas/monitoring.py \
    jiejing_saas/repository.py \
    jiejing_saas/worker.py
)

cat > "$release_dir/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt" <<EOF
SOURCE_COMMIT=$SOURCE_SHA
BUNDLE_SHA256=$BUNDLE_SHA256
MANIFEST_SHA256=$MANIFEST_SHA256
CREATED_AT=$STAMP
PREVIOUS_RELEASE=$previous_release
PRIVATE_DIR=$private_dir
DRY_RUN=$DRY_RUN
EOF
chmod 0644 "$release_dir/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"

export JIEJING_PRODUCTION_PRIVATE_DIR="$private_dir"
candidate_compose=(
  docker compose
  --project-name deploy
  --env-file "$private_dir/production-compose.env"
  -f "$candidate_app/deploy/docker-compose.production-pilot.yml"
)
previous_compose=(
  docker compose
  --project-name deploy
  --env-file "$private_dir/production-compose.env"
  -f "$active_app/deploy/docker-compose.production-pilot.yml"
)
"${candidate_compose[@]}" config --quiet

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "JIEJING_PRODUCTION_DEPLOY_DRY_RUN=1"
  printf 'SOURCE_COMMIT=%s\n' "$SOURCE_SHA"
  printf '%s\n' "CANDIDATE_RELEASE_PERSISTED=0"
  printf 'PREVIOUS_RELEASE=%s\n' "$previous_release"
  printf '%s\n' "ACTIVE_SWITCHED=0"
  exit 0
fi

wait_container_healthy() {
  local container="$1" attempts="${2:-60}" state
  for ((i=1; i<=attempts; i++)); do
    state="$(docker inspect "$container" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
    [[ "$state" == "healthy" || "$state" == "running" ]] && return 0
    sleep 2
  done
  return 1
}

wait_public_json() {
  local path="$1" attempts="${2:-45}" body
  for ((i=1; i<=attempts; i++)); do
    body="$(curl -fsS --max-time 10 -A 'Mozilla/5.0 JiejingProductionDeploy/1.0' "$PUBLIC_URL$path" 2>/dev/null || true)"
    if printf '%s' "$body" | python3 -c '
import json
import sys

path = sys.argv[1]
try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, OSError):
    raise SystemExit(1)

if path == "/health":
    ok = data.get("status") == "ok" and data.get("secret_exposed") is False
elif path == "/health/deep":
    health = data.get("operational_health") or {}
    ok = health.get("status") == "ready" and health.get("secret_exposed") is False
elif path == "/readiness/product-saas":
    readiness = data.get("readiness") or {}
    ok = (
        readiness.get("secret_exposed") is False
        and readiness.get("environment") == "production"
        and bool(readiness.get("public_contract_version"))
    )
else:
    ok = False
raise SystemExit(0 if ok else 1)
' "$path"; then
      return 0
    fi
    sleep 2
  done
  printf 'PRODUCTION_PUBLIC_CHECK_FAILED=%s\n' "$path" >&2
  return 1
}

build_candidate_images_with_retry() {
  local attempt
  for attempt in 1 2; do
    if "${candidate_compose[@]}" build jiejing-saas jiejing-worker; then
      return 0
    fi
    printf 'JIEJING_PRODUCTION_BUILD_RETRY=%s/2\n' "$attempt" >&2
    if [[ "$attempt" -lt 2 ]]; then
      sleep 5
    fi
  done
  return 1
}

unit_backup_dir="$release_dir/evidence-refresh-unit-backup"
wrapper_backup="$unit_backup_dir/wrapper"
service_backup="$unit_backup_dir/service"
timer_backup="$unit_backup_dir/timer"
old_wrapper_present=0
old_service_present=0
old_timer_present=0
old_timer_enabled="unknown"
old_timer_active="unknown"
old_timer_should_be_enabled=0
old_timer_should_be_active=0
unit_snapshot_complete=0
unit_mutation_started=0

snapshot_root_file() {
  local target="$1" backup="$2" presence_name="$3"
  if [[ -L "$target" || ( -e "$target" && ! -f "$target" ) ]]; then
    printf 'REFUSE_EVIDENCE_REFRESH_ROOT_TARGET_INVALID=%s\n' "$presence_name" >&2
    return 1
  fi
  if [[ -f "$target" ]]; then
    cp -a -- "$target" "$backup" || return 1
    printf -v "$presence_name" '%s' 1
  else
    printf -v "$presence_name" '%s' 0
  fi
}

snapshot_evidence_refresh_units() {
  install -d -m 0700 -o root -g root "$unit_backup_dir" || return 1
  old_timer_enabled="$(systemctl is-enabled "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)"
  old_timer_active="$(systemctl is-active "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)"
  case "$old_timer_enabled" in
    enabled|enabled-runtime|linked|linked-runtime) old_timer_should_be_enabled=1 ;;
    disabled|static|indirect|masked|generated|transient|not-found|alias) old_timer_should_be_enabled=0 ;;
    *) return 1 ;;
  esac
  case "$old_timer_active" in
    active|activating|reloading) old_timer_should_be_active=1 ;;
    inactive|failed|deactivating) old_timer_should_be_active=0 ;;
    *) return 1 ;;
  esac
  snapshot_root_file "$EVIDENCE_REFRESH_WRAPPER" "$wrapper_backup" old_wrapper_present || return 1
  snapshot_root_file "$EVIDENCE_REFRESH_SERVICE_PATH" "$service_backup" old_service_present || return 1
  snapshot_root_file "$EVIDENCE_REFRESH_TIMER_PATH" "$timer_backup" old_timer_present || return 1
  unit_snapshot_complete=1
}

atomic_install_root_file() {
  local source="$1" target="$2" mode="$3" temporary metadata
  temporary="${target}.jiejing-new.$$"
  [[ ! -e "$temporary" && ! -L "$temporary" ]] || return 1
  install -m "$mode" -o root -g root -- "$source" "$temporary" || return 1
  mv -fT -- "$temporary" "$target" || {
    rm -f -- "$temporary"
    return 1
  }
  metadata="$(stat -c '%U:%G %a' -- "$target" 2>/dev/null || true)"
  [[ "$metadata" == "root:root ${mode#0}" ]] || return 1
  cmp -s -- "$source" "$target"
}

restore_root_file() {
  local target="$1" backup="$2" was_present="$3" temporary
  temporary="${target}.jiejing-restore.$$"
  rm -f -- "${target}.jiejing-new.$$" "$temporary"
  if [[ "$was_present" == "1" ]]; then
    cp -a -- "$backup" "$temporary" || return 1
    mv -fT -- "$temporary" "$target" || return 1
  else
    rm -f -- "$target" || return 1
  fi
}

restore_evidence_refresh_units() {
  local restore_rc=0 restored_enabled
  if [[ "$unit_snapshot_complete" != "1" || "$unit_mutation_started" != "1" ]]; then
    return 0
  fi
  systemctl stop "$EVIDENCE_REFRESH_TIMER" >/dev/null 2>&1 || true
  systemctl stop "$EVIDENCE_REFRESH_SERVICE" >/dev/null 2>&1 || true
  systemctl disable "$EVIDENCE_REFRESH_TIMER" >/dev/null 2>&1 || true
  if [[ "$unit_mutation_started" == "1" && "$unit_snapshot_complete" == "1" ]]; then
    restore_root_file "$EVIDENCE_REFRESH_WRAPPER" "$wrapper_backup" "$old_wrapper_present" || restore_rc=1
    restore_root_file "$EVIDENCE_REFRESH_SERVICE_PATH" "$service_backup" "$old_service_present" || restore_rc=1
    restore_root_file "$EVIDENCE_REFRESH_TIMER_PATH" "$timer_backup" "$old_timer_present" || restore_rc=1
  fi
  systemctl daemon-reload >/dev/null 2>&1 || restore_rc=1
  case "$old_timer_enabled" in
    enabled|linked) systemctl enable "$EVIDENCE_REFRESH_TIMER" >/dev/null 2>&1 || restore_rc=1 ;;
    enabled-runtime|linked-runtime) systemctl enable --runtime "$EVIDENCE_REFRESH_TIMER" >/dev/null 2>&1 || restore_rc=1 ;;
  esac
  restored_enabled="$(systemctl is-enabled "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)"
  if [[ "$old_timer_should_be_enabled" == "1" ]]; then
    [[ "$restored_enabled" == "enabled" || "$restored_enabled" == "enabled-runtime" ]] || restore_rc=1
  else
    [[ "$restored_enabled" != "enabled" && "$restored_enabled" != "enabled-runtime" ]] || restore_rc=1
  fi
  return "$restore_rc"
}

restore_evidence_refresh_timer_activity() {
  local restored_active
  if [[ "$unit_snapshot_complete" != "1" || "$unit_mutation_started" != "1" ]]; then
    return 0
  fi
  if [[ "$old_timer_should_be_active" == "1" ]]; then
    systemctl start "$EVIDENCE_REFRESH_TIMER" >/dev/null 2>&1 || return 1
    restored_active="$(systemctl is-active "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)"
    [[ "$restored_active" == "active" ]]
  else
    systemctl stop "$EVIDENCE_REFRESH_TIMER" >/dev/null 2>&1 || true
    restored_active="$(systemctl is-active "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)"
    [[ "$restored_active" != "active" && "$restored_active" != "activating" ]]
  fi
}

verify_no_evidence_refresh_dropins() {
  local service_property timer_property
  service_property="$(systemctl show "$EVIDENCE_REFRESH_SERVICE" -p DropInPaths 2>/dev/null)" \
    || return 1
  timer_property="$(systemctl show "$EVIDENCE_REFRESH_TIMER" -p DropInPaths 2>/dev/null)" \
    || return 1
  if [[ "$service_property" != "DropInPaths=" || "$timer_property" != "DropInPaths=" ]]; then
    printf '%s\n' "REFUSE_EVIDENCE_REFRESH_DROPINS=1" >&2
    return 1
  fi
}

install_evidence_refresh_units() {
  local candidate_wrapper="$candidate_app/deploy/jiejing-production-evidence-auto-refresh.sh"
  local candidate_service="$candidate_app/deploy/systemd/jiejing-production-evidence-refresh.service"
  local candidate_timer="$candidate_app/deploy/systemd/jiejing-production-evidence-refresh.timer"

  snapshot_evidence_refresh_units || return 1
  install -d -m 0755 -o root -g root "$(dirname -- "$EVIDENCE_REFRESH_WRAPPER")" || return 1
  unit_mutation_started=1
  case "$old_timer_active" in
    active|activating|reloading) systemctl stop "$EVIDENCE_REFRESH_TIMER" || return 1 ;;
    *) systemctl stop "$EVIDENCE_REFRESH_TIMER" >/dev/null 2>&1 || true ;;
  esac
  atomic_install_root_file "$candidate_wrapper" "$EVIDENCE_REFRESH_WRAPPER" 0755 || return 1
  atomic_install_root_file "$candidate_service" "$EVIDENCE_REFRESH_SERVICE_PATH" 0644 || return 1
  atomic_install_root_file "$candidate_timer" "$EVIDENCE_REFRESH_TIMER_PATH" 0644 || return 1
  systemd-analyze verify "$EVIDENCE_REFRESH_SERVICE_PATH" "$EVIDENCE_REFRESH_TIMER_PATH" || return 1
  systemctl daemon-reload || return 1
  verify_no_evidence_refresh_dropins || return 1
  systemctl enable "$EVIDENCE_REFRESH_TIMER" || return 1
  [[ "$(systemctl is-enabled "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)" == "enabled" ]] || return 1
}

verify_first_evidence_refresh_oneshot() {
  local before_invocation after_invocation result exec_main_status journal_output attempt secret_safe_count
  before_invocation="$(systemctl show "$EVIDENCE_REFRESH_SERVICE" -p InvocationID --value 2>/dev/null || true)"
  systemctl start "$EVIDENCE_REFRESH_SERVICE" || return 1
  after_invocation="$(systemctl show "$EVIDENCE_REFRESH_SERVICE" -p InvocationID --value 2>/dev/null || true)"
  [[ "$after_invocation" =~ ^[0-9a-f]{32}$ ]] || return 1
  [[ "$after_invocation" != "$before_invocation" ]] || return 1
  result="$(systemctl show "$EVIDENCE_REFRESH_SERVICE" -p Result --value 2>/dev/null || true)"
  exec_main_status="$(systemctl show "$EVIDENCE_REFRESH_SERVICE" -p ExecMainStatus --value 2>/dev/null || true)"
  [[ "$result" == "success" && "$exec_main_status" == "0" ]] || return 1
  for attempt in 1 2 3 4 5; do
    journal_output="$(journalctl "_SYSTEMD_INVOCATION_ID=$after_invocation" -u "$EVIDENCE_REFRESH_SERVICE" --no-pager -o cat 2>/dev/null || true)"
    secret_safe_count="$(grep -Fxc 'SECRET_EXPOSED=false' <<<"$journal_output" || true)"
    if grep -Fqx 'JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success' <<<"$journal_output" \
      && [[ "$secret_safe_count" == "1" ]] \
      && ! grep -Fqx 'JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=skipped' <<<"$journal_output" \
      && ! grep -Fqx 'JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=blocked' <<<"$journal_output" \
      && ! grep -Fq 'JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=' <<<"$journal_output" \
      && ! grep -Fqx 'SECRET_EXPOSED=true' <<<"$journal_output"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_and_verify_evidence_refresh_timer() {
  local enabled active next_elapse
  systemctl start "$EVIDENCE_REFRESH_TIMER" || return 1
  enabled="$(systemctl is-enabled "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)"
  active="$(systemctl is-active "$EVIDENCE_REFRESH_TIMER" 2>/dev/null || true)"
  next_elapse="$(systemctl show "$EVIDENCE_REFRESH_TIMER" -p NextElapseUSecRealtime --value 2>/dev/null || true)"
  [[ "$enabled" == "enabled" && "$active" == "active" ]] || return 1
  case "$next_elapse" in
    ""|"n/a"|"0"|"[not set]") return 1 ;;
    *) return 0 ;;
  esac
}

fail_unit_transaction() {
  local original_rc="${1:-1}" restore_rc=0 activity_restore_rc=0
  if [[ "$unit_transaction_failure_in_progress" == "1" ]]; then
    exit "$original_rc"
  fi
  trap '' HUP INT TERM
  unit_transaction_failure_in_progress=1
  unit_transaction_active=0
  trap - EXIT
  set +e
  printf 'JIEJING_PRODUCTION_UNIT_TRANSACTION_FAILED_STAGE=%s\n' "$current_stage" >&2
  restore_evidence_refresh_units
  restore_rc=$?
  release_maintenance_lock
  if [[ "$restore_rc" == "0" ]]; then
    restore_evidence_refresh_timer_activity
    activity_restore_rc=$?
  fi
  release_deploy_lock
  printf '%s\n' "TIMER_INSTALL_ROLLED_BACK=1" >&2
  printf '%s\n' "APPLICATION_RELEASE_RETAINED=1" >&2
  if [[ "$restore_rc" != "0" || "$activity_restore_rc" != "0" ]]; then
    printf '%s\n' "TIMER_INSTALL_ROLLBACK_INCOMPLETE=1" >&2
  fi
  trap - HUP INT TERM
  exit "$original_rc"
}

unit_transaction_signal_handler() {
  local signal_name="$1" exit_code="$2"
  if [[ "$unit_transaction_active" == "1" && "$unit_transaction_failure_in_progress" == "0" ]]; then
    current_stage="unit_transaction_interrupted_${signal_name,,}"
    fail_unit_transaction "$exit_code"
  fi
  trap - HUP INT TERM EXIT
  exit "$exit_code"
}

unit_transaction_exit_handler() {
  local exit_code="${1:-1}"
  if [[ "$unit_transaction_active" == "1" && "$unit_transaction_failure_in_progress" == "0" ]]; then
    [[ "$exit_code" != "0" ]] || exit_code=1
    current_stage="unit_transaction_unexpected_exit"
    fail_unit_transaction "$exit_code"
  fi
}

arm_unit_transaction_traps() {
  unit_transaction_failure_in_progress=0
  unit_transaction_active=1
  trap 'unit_transaction_signal_handler HUP 129' HUP
  trap 'unit_transaction_signal_handler INT 130' INT
  trap 'unit_transaction_signal_handler TERM 143' TERM
  trap 'unit_transaction_exit_handler "$?"' EXIT
}

disarm_unit_transaction_traps() {
  unit_transaction_active=0
  trap - HUP INT TERM EXIT
}

rollback_on_error() {
  local code=$?
  trap - ERR
  set +e
  printf 'JIEJING_PRODUCTION_DEPLOY_FAILED_STAGE=%s\n' "$current_stage" >&2
  if [[ "$mutation_started" == "1" ]]; then
    "${previous_compose[@]}" build jiejing-saas jiejing-worker
    "${previous_compose[@]}" up -d --no-deps jiejing-saas
    wait_container_healthy deploy-jiejing-saas-1 60
    "${previous_compose[@]}" up -d --no-deps jiejing-worker
    "${previous_compose[@]}" up -d --no-deps --force-recreate jiejing-frontend
    "${previous_compose[@]}" up -d --no-deps --force-recreate jiejing-edge
    ln -sfnT "$active_app" "$ACTIVE_LINK"
    printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1" >&2
  else
    printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_NOT_REQUIRED=1" >&2
  fi
  release_maintenance_lock
  release_deploy_lock
  exit "$code"
}
trap rollback_on_error ERR

current_stage="build_candidate_images"
build_candidate_images_with_retry
mutation_started=1
current_stage="start_candidate_api"
"${candidate_compose[@]}" up -d --no-deps jiejing-saas
wait_container_healthy deploy-jiejing-saas-1 60
current_stage="start_candidate_worker"
"${candidate_compose[@]}" up -d --no-deps jiejing-worker
wait_container_healthy deploy-jiejing-worker-1 30
current_stage="start_candidate_frontend"
"${candidate_compose[@]}" up -d --no-deps --force-recreate jiejing-frontend
current_stage="start_candidate_edge"
"${candidate_compose[@]}" up -d --no-deps --force-recreate jiejing-edge
wait_container_healthy deploy-jiejing-frontend-1 30
wait_container_healthy deploy-jiejing-edge-1 30
current_stage="verify_public_health"
wait_public_json "/health" 45
current_stage="verify_public_deep_health"
wait_public_json "/health/deep" 45
current_stage="verify_public_product_readiness"
wait_public_json "/readiness/product-saas" 45
current_stage="activate_release"
ln -sfnT "$candidate_app" "$ACTIVE_LINK"
mutation_started=0
trap - ERR

current_stage="install_evidence_refresh_units"
arm_unit_transaction_traps
unit_rc=0
install_evidence_refresh_units || unit_rc=$?
if [[ "$unit_rc" != "0" ]]; then
  fail_unit_transaction "$unit_rc"
fi

# The service itself takes the shared maintenance lock. Release only that lock
# after installation and enablement; keep the deploy-only lock until the first
# invocation and timer schedule have both been verified.
release_maintenance_lock
current_stage="verify_first_evidence_refresh_oneshot"
unit_rc=0
verify_first_evidence_refresh_oneshot || unit_rc=$?
if [[ "$unit_rc" != "0" ]]; then
  fail_unit_transaction "$unit_rc"
fi
printf '%s\n' "TIMER_FIRST_ONESHOT_VERIFIED=1"

current_stage="start_evidence_refresh_timer"
unit_rc=0
start_and_verify_evidence_refresh_timer || unit_rc=$?
if [[ "$unit_rc" != "0" ]]; then
  fail_unit_transaction "$unit_rc"
fi
printf '%s\n' "TIMER_INSTALL_APPLIED=1"
disarm_unit_transaction_traps
release_deploy_lock

printf '%s\n' "JIEJING_PRODUCTION_DEPLOY_APPLIED=1"
printf 'SOURCE_COMMIT=%s\n' "$SOURCE_SHA"
printf 'RELEASE_DIR=%s\n' "$release_dir"
printf 'PREVIOUS_RELEASE=%s\n' "$previous_release"
printf 'PRIVATE_DIR=%s\n' "$private_dir"
