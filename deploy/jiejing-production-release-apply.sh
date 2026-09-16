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
ROLLBACK_API_HOLD_REF="jiejing-production-rollback-api:previous"
ROLLBACK_WORKER_HOLD_REF="jiejing-production-rollback-worker:previous"
ROLLBACK_API_HOLD_BACKUP_REF="jiejing-production-rollback-api:capture-backup"
ROLLBACK_WORKER_HOLD_BACKUP_REF="jiejing-production-rollback-worker:capture-backup"
mutation_started=0
active_switched=0
current_stage="preflight"
deploy_lock_held=0
maintenance_lock_held=0
unit_transaction_active=0
unit_transaction_failure_in_progress=0
dry_run_candidate=""
dry_run_cleanup_active=0
previous_api_hold_image_id=""
previous_worker_hold_image_id=""
previous_api_hold_existed=0
previous_worker_hold_existed=0
rollback_image_holds_ready=0
candidate_api_image_id=""
candidate_worker_image_id=""
previous_ops_supported=0

refuse() {
  printf '%s\n' "$1" >&2
  exit "${2:-1}"
}

verify_ops_stored_certificates() {
  # Public certificates only. Private key contents are never opened here.
  # A separate reviewed import binds each keypair; post-start TLS verifies it.
  python3 - <<'PY'
import os, stat, subprocess
from pathlib import Path

root = Path('/var/lib/docker/volumes/deploy_jiejing_caddy_data/_data/caddy/certificates')
issuers = ('acme-v02.api.letsencrypt.org-directory', 'acme.zerossl.com-v2-DV90')
def safe(path):
    snapshot = []
    for part in (path, *path.parents):
        value = part.lstat()
        # The official Caddy image initializes only its data/caddy root as
        # root-owned 01777. Never extend this exception to its descendants.
        caddy_storage = (str(part) == '/var/lib/docker/volumes/deploy_jiejing_caddy_data/_data/caddy'
                         and stat.S_ISDIR(value.st_mode) and value.st_uid == value.st_gid == 0
                         and stat.S_IMODE(value.st_mode) == 0o1777)
        if stat.S_ISLNK(value.st_mode) or value.st_uid != 0 or (value.st_mode & 0o022 and not caddy_storage):
            return None
        snapshot.append((part, identity(value)))
    return snapshot
def run(args):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
                          env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'})
def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)
try:
    for host in ('ops.jiejing.shop', 'jiejing.shop'):
        found = False
        for issuer in issuers:
            cert = root / issuer / host / (host + '.crt')
            key = cert.with_suffix('.key')
            if not cert.exists() or not key.exists():
                continue
            cert_path, key_path = safe(cert), safe(key)
            if not cert_path or not key_path:
                raise ValueError()
            ci, ki = cert.lstat(), key.lstat()
            if not stat.S_ISREG(ci.st_mode) or not stat.S_ISREG(ki.st_mode) or not 1 <= ci.st_size <= 262144 or not 1 <= ki.st_size <= 65536 or stat.S_IMODE(ki.st_mode) != 0o600:
                raise ValueError()
            san = run(['openssl','x509','-in',str(cert),'-noout','-ext','subjectAltName'])
            names = {x.strip() for x in san.stdout.decode('ascii').replace('\n', ',').split(',')}
            if san.returncode or 'DNS:' + host not in names:
                continue
            expiry = run(['openssl','x509','-in',str(cert),'-noout','-checkend','604800'])
            chain = run(['openssl','verify','-purpose','sslserver','-verify_hostname',host,
                         '-CApath','/etc/ssl/certs','-untrusted',str(cert),str(cert)])
            if expiry.returncode or chain.returncode:
                continue
            if identity(cert.lstat()) != identity(ci) or identity(key.lstat()) != identity(ki):
                raise ValueError()
            if any(identity(part.lstat()) != before for part, before in (*cert_path, *key_path)):
                raise ValueError()
            found = True
        if not found:
            raise ValueError()
except Exception:
    raise SystemExit(1) from None
PY
}

ops_dns_points_to_old_host() {
  # Only the DNS-only operations A record is used for this transition gate.
  # The proxied apex cannot be classified from its public Cloudflare IPs.
  timeout --signal=TERM --kill-after=2 15 python3 - <<'PY'
import socket
try:
    addresses = {row[4][0] for row in socket.getaddrinfo('ops.jiejing.shop', 443, type=socket.SOCK_STREAM)}
    raise SystemExit(0 if addresses == {'43.129.205.244'} else 1)
except Exception:
    raise SystemExit(1) from None
PY
}

stop_candidate_ops_if_owned() {
  local config container_id
  container_id="$(docker ps -aq --no-trunc --filter 'name=^/deploy-jiejing-ops-frontend-1$' 2>/dev/null)" || return 1
  [[ -n "$container_id" ]] || return 0
  [[ "$container_id" =~ ^[0-9a-f]{64}$ ]] || return 1
  config="$(docker inspect "$container_id" --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' 2>/dev/null)" || return 1
  [[ "$config" == "$candidate_app/deploy/docker-compose.production-pilot.yml" ]] || return 1
  docker stop --time 30 "$container_id" >/dev/null 2>&1
}

verify_ops_surface() {
  local source_app="$1" name expected actual code redirect
  local -a local_tls=(--noproxy '*' --resolve ops.jiejing.shop:443:127.0.0.1 --max-time 10 --max-filesize 2097152 -A 'Mozilla/5.0 JiejingProductionOps/1.0')
  for name in ops.html ops.js ops.css assets/jiejing-logo-mark.svg assets/jiejing-app-icon.svg assets/jiejing-ops-panels.js; do
    expected="$(sha256sum -- "$source_app/$name" 2>/dev/null | cut -d' ' -f1)" || { printf '%s\n' 'OPS_SURFACE_FAILED=asset_source_hash' >&2; return 1; }
    actual="$(curl -fsS "${local_tls[@]}" "https://ops.jiejing.shop/$name" 2>/dev/null | sha256sum | cut -d' ' -f1)" || { printf '%s\n' 'OPS_SURFACE_FAILED=asset_tls_or_http' >&2; return 1; }
    [[ "$actual" == "$expected" ]] || { printf '%s\n' 'OPS_SURFACE_FAILED=asset_hash' >&2; return 1; }
  done
  for name in /owner/operations-overview /owner/billing/domestic/refunds /permissions/me; do
    code="$(curl -sS "${local_tls[@]}" -o /dev/null -w '%{http_code}' "https://ops.jiejing.shop$name" 2>/dev/null)" || { printf '%s\n' 'OPS_SURFACE_FAILED=anonymous_request' >&2; return 1; }
    [[ "$code" == "401" || "$code" == "403" ]] || { printf '%s\n' 'OPS_SURFACE_FAILED=anonymous_auth' >&2; return 1; }
  done
  for name in /owner/not-allowlisted /app.html; do
    code="$(curl -sS "${local_tls[@]}" -o /dev/null -w '%{http_code}' "https://ops.jiejing.shop$name" 2>/dev/null)" || { printf '%s\n' 'OPS_SURFACE_FAILED=ops_isolation_request' >&2; return 1; }
    [[ "$code" == "404" ]] || { printf '%s\n' 'OPS_SURFACE_FAILED=ops_isolation' >&2; return 1; }
  done
  for name in /ops.html /ops.js /ops.css /assets/jiejing-ops-panels.js /owner/operations-overview; do
    code="$(curl -sS --noproxy '*' --resolve app.jiejing.shop:443:127.0.0.1 --max-time 10 -o /dev/null -w '%{http_code}' "https://app.jiejing.shop$name" 2>/dev/null)" || { printf '%s\n' 'OPS_SURFACE_FAILED=app_isolation_request' >&2; return 1; }
    [[ "$code" == "404" ]] || { printf '%s\n' 'OPS_SURFACE_FAILED=app_isolation' >&2; return 1; }
  done
  redirect="$(curl -sS --noproxy '*' --resolve jiejing.shop:443:127.0.0.1 --max-time 10 -o /dev/null -w '%{http_code} %{redirect_url}' 'https://jiejing.shop/migration-check?source=ops' 2>/dev/null)" || { printf '%s\n' 'OPS_SURFACE_FAILED=apex_request' >&2; return 1; }
  [[ "$redirect" == '301 https://app.jiejing.shop/migration-check?source=ops' ]] || { printf '%s\n' 'OPS_SURFACE_FAILED=apex_redirect' >&2; return 1; }
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

resolve_manifest_private_dir() {
  local release="$1" label_environment_file="$2" manifest count manifest_private resolved_private resolved_environment private_parent
  manifest="$release/JIEJING_PRODUCTION_RELEASE_MANIFEST.txt"
  [[ -f "$manifest" && ! -L "$manifest" ]] || return 1
  count="$(awk -F= '$1 == "PRIVATE_DIR" {count += 1} END {print count + 0}' "$manifest" 2>/dev/null || true)"
  [[ "$count" == "1" ]] || return 1
  manifest_private="$(awk -F= '$1 == "PRIVATE_DIR" {print substr($0, index($0, "=") + 1)}' "$manifest" 2>/dev/null || true)"
  [[ "$manifest_private" == /* && "$manifest_private" != *$'\n'* && "$manifest_private" != *$'\r'* ]] || return 1
  resolved_private="$(readlink -f -- "$manifest_private" 2>/dev/null || true)"
  [[ "$resolved_private" == "$manifest_private" && -d "$resolved_private" && ! -L "$resolved_private" ]] || return 1
  if [[ "$resolved_private" != "$PRODUCTION_ROOT/private" ]]; then
    [[ "$(basename -- "$resolved_private")" == "private" ]] || return 1
    private_parent="$(dirname -- "$resolved_private")"
    [[ "$(dirname -- "$private_parent")" == "$RELEASE_ROOT" ]] || return 1
  fi
  resolved_environment="$(readlink -f -- "$label_environment_file" 2>/dev/null || true)"
  [[ "$resolved_environment" == "$label_environment_file" ]] || return 1
  [[ "$resolved_environment" == "$resolved_private/production-compose.env" ]] || return 1
  [[ -f "$resolved_environment" && ! -L "$resolved_environment" ]] || return 1
  [[ -f "$resolved_private/jiejing-saas.production.env" && ! -L "$resolved_private/jiejing-saas.production.env" ]] || return 1
  [[ "$(readlink -f -- "$resolved_private/jiejing-saas.production.env" 2>/dev/null || true)" == "$resolved_private/jiejing-saas.production.env" ]] || return 1
  private_dir="$resolved_private"
  COMPOSE_ENV="$resolved_environment"
  APP_ENV="$resolved_private/jiejing-saas.production.env"
}

private_env_permissions_ready() {
  local directory_metadata compose_metadata app_metadata
  directory_metadata="$(stat -c '%U:%G %a' -- "$private_dir" 2>/dev/null || true)"
  compose_metadata="$(stat -c '%U:%G %a' -- "$COMPOSE_ENV" 2>/dev/null || true)"
  app_metadata="$(stat -c '%U:%G %a' -- "$APP_ENV" 2>/dev/null || true)"
  [[ "$directory_metadata" == "root:root 700" ]] \
    && [[ "$compose_metadata" == "root:root 600" ]] \
    && [[ "$app_metadata" == "root:root 600" ]]
}

assess_private_env_normalization() {
  if private_env_permissions_ready; then
    private_env_normalization_required=0
  else
    private_env_normalization_required=1
  fi
  printf 'PRIVATE_ENV_NORMALIZATION_REQUIRED=%s\n' "$private_env_normalization_required"
  printf 'PRIVATE_ENV_NORMALIZATION_PLANNED=%s\n' "$private_env_normalization_required"
}

normalize_private_env_permissions() {
  python3 - "$private_dir" "$COMPOSE_ENV" "$APP_ENV" <<'PY'
from __future__ import annotations

import os
import stat
import sys


private_dir, compose_env, app_env = sys.argv[1:]
expected = {
    compose_env: 0o600,
    app_env: 0o600,
}
directory_fd = -1
file_fds: list[int] = []
snapshots: list[tuple[int, int, int, int]] = []
mutation_started = False


def restore() -> bool:
    restored = True
    for fd, uid, gid, mode in reversed(snapshots):
        try:
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
        except OSError:
            restored = False
    return restored


try:
    directory_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_stat = os.fstat(directory_fd)
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_mode & 0o022:
        raise OSError("unsafe_private_directory")
    snapshots.append((directory_fd, directory_stat.st_uid, directory_stat.st_gid, stat.S_IMODE(directory_stat.st_mode)))
    for path, target_mode in expected.items():
        name = os.path.basename(path)
        if os.path.dirname(path) != private_dir or name not in {"production-compose.env", "jiejing-saas.production.env"}:
            raise OSError("unsafe_private_file_path")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        file_fds.append(fd)
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_mode & 0o077:
            raise OSError("unsafe_private_file")
        snapshots.append((fd, metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)))
    mutation_started = True
    os.fchown(directory_fd, 0, 0)
    os.fchmod(directory_fd, 0o700)
    for fd, _uid, _gid, _mode in snapshots[1:]:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
    normalized_directory = os.fstat(directory_fd)
    if (normalized_directory.st_uid, normalized_directory.st_gid, stat.S_IMODE(normalized_directory.st_mode)) != (0, 0, 0o700):
        raise OSError("private_directory_normalization_failed")
    for fd in file_fds:
        normalized_file = os.fstat(fd)
        if (
            normalized_file.st_uid,
            normalized_file.st_gid,
            stat.S_IMODE(normalized_file.st_mode),
            normalized_file.st_nlink,
        ) != (0, 0, 0o600, 1):
            raise OSError("private_file_normalization_failed")
except OSError:
    if mutation_started:
        if restore():
            print("PRIVATE_ENV_NORMALIZATION_ROLLED_BACK=1", file=sys.stderr)
        else:
            print("PRIVATE_ENV_NORMALIZATION_ROLLBACK_INCOMPLETE=1", file=sys.stderr)
    raise SystemExit(1)
finally:
    for fd in reversed(file_fds):
        try:
            os.close(fd)
        except OSError:
            pass
    if directory_fd >= 0:
        try:
            os.close(directory_fd)
        except OSError:
            pass
PY
  resolve_manifest_private_dir "$previous_release" "$environment_file" \
    && private_env_permissions_ready
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

acquire_maintenance_lock_for_rollback() {
  if [[ "$maintenance_lock_held" == "1" ]]; then
    return 0
  fi
  command -v flock >/dev/null 2>&1 || return 1
  if ! exec 9>"$MAINTENANCE_LOCK"; then
    return 1
  fi
  if flock -w 60 9; then
    maintenance_lock_held=1
    return 0
  fi
  exec 9>&-
  return 1
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
resolve_manifest_private_dir "$previous_release" "$environment_file" \
  || refuse "REFUSE_PRIVATE_MANIFEST_CONTRACT=1" 25
[[ -f "$private_dir/jiejing-vault-token.d/jiejing-vault-token" && ! -L "$private_dir/jiejing-vault-token.d/jiejing-vault-token" ]] || refuse "REFUSE_PRIVATE_VAULT_TOKEN_MISSING=1" 28
private_env_normalization_required=0
assess_private_env_normalization
private_env_normalization_applied=0

if grep -q '^  jiejing-ops-frontend:' "$active_app/deploy/docker-compose.production-pilot.yml" \
  && grep -Fqx 'ops.jiejing.shop {' "$active_app/deploy/Caddyfile.production" \
  && grep -Fqx 'jiejing.shop {' "$active_app/deploy/Caddyfile.production"; then
  previous_ops_supported=1
else
  ops_dns_points_to_old_host || refuse "REFUSE_OPS_TRANSITION_DNS_CUTBACK_REQUIRED=1" 40
fi
verify_ops_stored_certificates || refuse "REFUSE_OPS_CERTIFICATE_PREFLIGHT=1" 40
printf 'OPS_PREVIOUS_RELEASE_SUPPORTED=%s\n' "$previous_ops_supported"
printf '%s\n' 'OPS_STORED_CERTIFICATE_PREFLIGHT=1'

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
  printf '%s\n' "PRIVATE_ENV_NORMALIZATION_APPLIED=0"
  printf '%s\n' "EVIDENCE_SNAPSHOT_INITIALIZED=0"
  printf '%s\n' "OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=0"
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

image_ref_id() {
  docker image inspect "$1" --format '{{.Id}}' 2>/dev/null || true
}

remove_image_ref_if_present() {
  local ref="$1"
  if [[ -n "$(image_ref_id "$ref")" ]]; then
    docker image rm "$ref" >/dev/null 2>&1 || return 1
  fi
  [[ -z "$(image_ref_id "$ref")" ]]
}

discard_prior_rollback_hold_backups() {
  local discard_rc=0
  remove_image_ref_if_present "$ROLLBACK_API_HOLD_BACKUP_REF" || discard_rc=1
  remove_image_ref_if_present "$ROLLBACK_WORKER_HOLD_BACKUP_REF" || discard_rc=1
  [[ "$discard_rc" == "0" ]]
}

prepare_prior_rollback_hold_backups() {
  local backup_rc=0
  discard_prior_rollback_hold_backups || return 1
  if [[ "$previous_api_hold_existed" == "1" ]]; then
    docker image tag "$previous_api_hold_image_id" "$ROLLBACK_API_HOLD_BACKUP_REF" || backup_rc=1
  fi
  if [[ "$backup_rc" == "0" && "$previous_worker_hold_existed" == "1" ]]; then
    docker image tag "$previous_worker_hold_image_id" "$ROLLBACK_WORKER_HOLD_BACKUP_REF" || backup_rc=1
  fi
  if [[ "$backup_rc" == "0" && "$previous_api_hold_existed" == "1" ]]; then
    [[ "$(image_ref_id "$ROLLBACK_API_HOLD_BACKUP_REF")" == "$previous_api_hold_image_id" ]] || backup_rc=1
  fi
  if [[ "$backup_rc" == "0" && "$previous_worker_hold_existed" == "1" ]]; then
    [[ "$(image_ref_id "$ROLLBACK_WORKER_HOLD_BACKUP_REF")" == "$previous_worker_hold_image_id" ]] || backup_rc=1
  fi
  if [[ "$backup_rc" != "0" ]]; then
    discard_prior_rollback_hold_backups || true
    return 1
  fi
}

restore_prior_rollback_image_holds() {
  local rollback_rc=0 current
  if [[ "$previous_api_hold_existed" == "1" ]]; then
    current="$(image_ref_id "$ROLLBACK_API_HOLD_REF")"
    if [[ "$current" != "$previous_api_hold_image_id" ]]; then
      if [[ "$(image_ref_id "$ROLLBACK_API_HOLD_BACKUP_REF")" == "$previous_api_hold_image_id" ]]; then
        docker image tag "$ROLLBACK_API_HOLD_BACKUP_REF" "$ROLLBACK_API_HOLD_REF" || rollback_rc=1
      else
        rollback_rc=1
      fi
    fi
  else
    current="$(image_ref_id "$ROLLBACK_API_HOLD_REF")"
    if [[ -n "$current" ]]; then
      docker image rm "$ROLLBACK_API_HOLD_REF" >/dev/null 2>&1 || rollback_rc=1
    fi
  fi
  if [[ "$previous_worker_hold_existed" == "1" ]]; then
    current="$(image_ref_id "$ROLLBACK_WORKER_HOLD_REF")"
    if [[ "$current" != "$previous_worker_hold_image_id" ]]; then
      if [[ "$(image_ref_id "$ROLLBACK_WORKER_HOLD_BACKUP_REF")" == "$previous_worker_hold_image_id" ]]; then
        docker image tag "$ROLLBACK_WORKER_HOLD_BACKUP_REF" "$ROLLBACK_WORKER_HOLD_REF" || rollback_rc=1
      else
        rollback_rc=1
      fi
    fi
  else
    current="$(image_ref_id "$ROLLBACK_WORKER_HOLD_REF")"
    if [[ -n "$current" ]]; then
      docker image rm "$ROLLBACK_WORKER_HOLD_REF" >/dev/null 2>&1 || rollback_rc=1
    fi
  fi
  if [[ "$previous_api_hold_existed" == "1" ]]; then
    [[ "$(image_ref_id "$ROLLBACK_API_HOLD_REF")" == "$previous_api_hold_image_id" ]] || rollback_rc=1
  else
    [[ -z "$(image_ref_id "$ROLLBACK_API_HOLD_REF")" ]] || rollback_rc=1
  fi
  if [[ "$previous_worker_hold_existed" == "1" ]]; then
    [[ "$(image_ref_id "$ROLLBACK_WORKER_HOLD_REF")" == "$previous_worker_hold_image_id" ]] || rollback_rc=1
  else
    [[ -z "$(image_ref_id "$ROLLBACK_WORKER_HOLD_REF")" ]] || rollback_rc=1
  fi
  discard_prior_rollback_hold_backups || rollback_rc=1
  [[ "$rollback_rc" == "0" ]]
}

capture_previous_runtime_images() {
  local hold_rc=0
  previous_api_image_id="$(docker inspect deploy-jiejing-saas-1 --format '{{.Image}}' 2>/dev/null || true)"
  previous_worker_image_id="$(docker inspect deploy-jiejing-worker-1 --format '{{.Image}}' 2>/dev/null || true)"
  previous_api_image_ref="$(docker inspect deploy-jiejing-saas-1 --format '{{.Config.Image}}' 2>/dev/null || true)"
  previous_worker_image_ref="$(docker inspect deploy-jiejing-worker-1 --format '{{.Config.Image}}' 2>/dev/null || true)"
  [[ "$previous_api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  [[ "$previous_worker_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  [[ "$previous_api_image_ref" =~ ^deploy-jiejing-saas(:latest)?$ ]] || return 1
  [[ "$previous_worker_image_ref" =~ ^deploy-jiejing-worker(:latest)?$ ]] || return 1
  docker image inspect "$previous_api_image_id" >/dev/null 2>&1 || return 1
  docker image inspect "$previous_worker_image_id" >/dev/null 2>&1 || return 1
  verify_runtime_labels_and_health "$active_app" "$previous_api_image_id" "$previous_worker_image_id" || return 1

  previous_api_hold_image_id="$(image_ref_id "$ROLLBACK_API_HOLD_REF")"
  previous_worker_hold_image_id="$(image_ref_id "$ROLLBACK_WORKER_HOLD_REF")"
  previous_api_hold_existed=0
  previous_worker_hold_existed=0
  if [[ -n "$previous_api_hold_image_id" ]]; then
    [[ "$previous_api_hold_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    previous_api_hold_existed=1
  fi
  if [[ -n "$previous_worker_hold_image_id" ]]; then
    [[ "$previous_worker_hold_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    previous_worker_hold_existed=1
  fi

  rollback_image_holds_ready=0
  prepare_prior_rollback_hold_backups || return 1
  docker image tag "$previous_api_image_id" "$ROLLBACK_API_HOLD_REF" || hold_rc=1
  if [[ "$hold_rc" == "0" ]]; then
    docker image tag "$previous_worker_image_id" "$ROLLBACK_WORKER_HOLD_REF" || hold_rc=1
  fi
  if [[ "$hold_rc" == "0" ]]; then
    [[ "$(image_ref_id "$ROLLBACK_API_HOLD_REF")" == "$previous_api_image_id" ]] || hold_rc=1
    [[ "$(image_ref_id "$ROLLBACK_WORKER_HOLD_REF")" == "$previous_worker_image_id" ]] || hold_rc=1
  fi
  if [[ "$hold_rc" != "0" ]]; then
    restore_prior_rollback_image_holds || printf '%s\n' "REFUSE_ROLLBACK_IMAGE_HOLD_RESTORE_FAILED=1" >&2
    return 1
  fi
  discard_prior_rollback_hold_backups || true
  rollback_image_holds_ready=1
  printf '%s\n' "ROLLBACK_IMAGE_HOLDS_VERIFIED=1"
}

capture_candidate_runtime_images() {
  candidate_api_image_id="$(image_ref_id "$previous_api_image_ref")"
  candidate_worker_image_id="$(image_ref_id "$previous_worker_image_ref")"
  [[ "$candidate_api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  [[ "$candidate_worker_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  docker image inspect "$candidate_api_image_id" >/dev/null 2>&1 || return 1
  docker image inspect "$candidate_worker_image_id" >/dev/null 2>&1 || return 1
}

runtime_evidence_result_verified() {
  python3 -c '
import json, re, sys
def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result
try:
    data = json.load(sys.stdin, object_pairs_hook=unique_pairs)
except (ValueError, OSError, UnicodeError):
    raise SystemExit(1)
mode = sys.argv[1]
base = isinstance(data, dict) and data.get("contract_version") == "jiejing_runtime_evidence_snapshot_v1" and data.get("secret_exposed") is False
if mode in {"prepared", "capable"}:
    valid = base and set(data) == {"status", "contract_version", "writes_snapshot", "secret_exposed"} and data.get("status") == mode and data.get("writes_snapshot") is False
else:
    valid = base and set(data) == {"status", "contract_version", "evidence_sha256", "secret_exposed"} and data.get("status") == "verified" and isinstance(data.get("evidence_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", data["evidence_sha256"]) is not None
raise SystemExit(0 if valid else 1)
' "$1"
}

initialize_runtime_evidence_snapshot() {
  local evidence_result image
  local evidence_directory="/opt/jiejing-production/runtime-evidence"
  # Preparation validates existing paths; it never chmods an untrusted target.
  evidence_result="$(python3 "$candidate_app/tools/jiejing_runtime_evidence_snapshot.py" \
    --prepare-directory --output-dir "$evidence_directory" 2>/dev/null)" || return 1
  runtime_evidence_result_verified prepared <<<"$evidence_result" || return 1
  unset evidence_result
  for image in "$candidate_api_image_id" "$candidate_worker_image_id"; do
    evidence_result="$(docker run --rm --network none -w /app "$image" \
      python tools/jiejing_runtime_evidence_snapshot.py --check-capability 2>/dev/null)" || return 1
    runtime_evidence_result_verified capable <<<"$evidence_result" || return 1
    unset evidence_result
  done
  # Only the exact candidate image exports already-recorded evidence. No probe,
  # live provider, environment rewrite, or deployment-time success timestamp.
  evidence_result="$(docker run --rm --network none \
    --mount "type=bind,src=$private_dir,dst=/private,readonly" \
    --mount "type=bind,src=$evidence_directory,dst=/runtime-evidence" \
    -w /app "$candidate_api_image_id" python tools/jiejing_runtime_evidence_snapshot.py \
    --env-file /private/jiejing-saas.production.env --output-dir /runtime-evidence 2>/dev/null)" || return 1
  runtime_evidence_result_verified verified <<<"$evidence_result" || return 1
  unset evidence_result
  printf '%s\n' "EVIDENCE_SNAPSHOT_INITIALIZED=1"
}

verify_runtime_labels_and_health() {
  local expected_app="$1" expected_api_image="$2" expected_worker_image="$3"
  local api_image worker_image api_state api_health worker_state api_config worker_config api_workdir worker_workdir api_env worker_env
  api_image="$(docker inspect deploy-jiejing-saas-1 --format '{{.Image}}' 2>/dev/null || true)"
  worker_image="$(docker inspect deploy-jiejing-worker-1 --format '{{.Image}}' 2>/dev/null || true)"
  api_state="$(docker inspect deploy-jiejing-saas-1 --format '{{.State.Status}}' 2>/dev/null || true)"
  api_health="$(docker inspect deploy-jiejing-saas-1 --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true)"
  worker_state="$(docker inspect deploy-jiejing-worker-1 --format '{{.State.Status}}' 2>/dev/null || true)"
  api_config="$(docker inspect deploy-jiejing-saas-1 --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' 2>/dev/null || true)"
  worker_config="$(docker inspect deploy-jiejing-worker-1 --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' 2>/dev/null || true)"
  api_workdir="$(docker inspect deploy-jiejing-saas-1 --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null || true)"
  worker_workdir="$(docker inspect deploy-jiejing-worker-1 --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null || true)"
  api_env="$(docker inspect deploy-jiejing-saas-1 --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' 2>/dev/null || true)"
  worker_env="$(docker inspect deploy-jiejing-worker-1 --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' 2>/dev/null || true)"
  [[ "$api_image" == "$expected_api_image" && "$worker_image" == "$expected_worker_image" ]] || return 1
  [[ "$api_state" == "running" && "$api_health" == "healthy" && "$worker_state" == "running" ]] || return 1
  [[ "$(readlink -f -- "$api_config" 2>/dev/null || true)" == "$expected_app/deploy/docker-compose.production-pilot.yml" ]] || return 1
  [[ "$(readlink -f -- "$worker_config" 2>/dev/null || true)" == "$expected_app/deploy/docker-compose.production-pilot.yml" ]] || return 1
  [[ "$(readlink -f -- "$api_workdir" 2>/dev/null || true)" == "$expected_app/deploy" ]] || return 1
  [[ "$(readlink -f -- "$worker_workdir" 2>/dev/null || true)" == "$expected_app/deploy" ]] || return 1
  [[ "$api_env" == "$environment_file" && "$worker_env" == "$environment_file" ]] || return 1
}

verify_candidate_runtime_image_coherence() {
  local api_image worker_image
  api_image="$(docker inspect deploy-jiejing-saas-1 --format '{{.Image}}' 2>/dev/null || true)"
  worker_image="$(docker inspect deploy-jiejing-worker-1 --format '{{.Image}}' 2>/dev/null || true)"
  [[ "$api_image" == "$candidate_api_image_id" && "$worker_image" == "$candidate_worker_image_id" ]] || return 1
  verify_runtime_labels_and_health "$candidate_app" "$candidate_api_image_id" "$candidate_worker_image_id" || return 1
  printf '%s\n' "CANDIDATE_RUNTIME_IMAGE_COHERENCE=verified"
}

atomic_replace_active_link() {
  local target="$1" expected_current="$2" current temporary resolved_target
  current="$(readlink -f -- "$ACTIVE_LINK" 2>/dev/null || true)"
  [[ "$current" == "$expected_current" ]] || return 1
  resolved_target="$(readlink -f -- "$target" 2>/dev/null || true)"
  [[ "$resolved_target" == "$target" && -d "$target" ]] || return 1
  temporary="${ACTIVE_LINK}.jiejing-new.$$"
  [[ ! -e "$temporary" && ! -L "$temporary" ]] || return 1
  ln -s -- "$target" "$temporary" || return 1
  if [[ "$(readlink -f -- "$temporary" 2>/dev/null || true)" != "$target" ]]; then
    rm -f -- "$temporary"
    return 1
  fi
  mv -Tf -- "$temporary" "$ACTIVE_LINK" || {
    rm -f -- "$temporary"
    return 1
  }
  [[ -L "$ACTIVE_LINK" && "$(readlink -f -- "$ACTIVE_LINK" 2>/dev/null || true)" == "$target" ]]
}

verify_previous_runtime_restored() {
  verify_runtime_labels_and_health "$active_app" "$previous_api_image_id" "$previous_worker_image_id"
}

rollback_application_release() {
  local rollback_rc=0 current_active
  [[ "$rollback_image_holds_ready" == "1" ]] || rollback_rc=1
  [[ "$(image_ref_id "$ROLLBACK_API_HOLD_REF")" == "$previous_api_image_id" ]] || rollback_rc=1
  [[ "$(image_ref_id "$ROLLBACK_WORKER_HOLD_REF")" == "$previous_worker_image_id" ]] || rollback_rc=1
  if [[ "$rollback_rc" == "0" ]]; then
    docker image tag "$ROLLBACK_API_HOLD_REF" "$previous_api_image_ref" || rollback_rc=1
    docker image tag "$ROLLBACK_WORKER_HOLD_REF" "$previous_worker_image_ref" || rollback_rc=1
  fi
  [[ "$(image_ref_id "$previous_api_image_ref")" == "$previous_api_image_id" ]] || rollback_rc=1
  [[ "$(image_ref_id "$previous_worker_image_ref")" == "$previous_worker_image_id" ]] || rollback_rc=1
  [[ "$rollback_rc" == "0" ]] || return 1
  "${previous_compose[@]}" up -d --no-build --no-deps --force-recreate jiejing-saas || rollback_rc=1
  wait_container_healthy deploy-jiejing-saas-1 60 || rollback_rc=1
  "${previous_compose[@]}" up -d --no-build --no-deps --force-recreate jiejing-worker || rollback_rc=1
  wait_container_healthy deploy-jiejing-worker-1 30 || rollback_rc=1
  "${previous_compose[@]}" up -d --no-deps --force-recreate jiejing-frontend || rollback_rc=1
  if [[ "${previous_ops_supported:-0}" == "1" ]]; then
    "${previous_compose[@]}" up -d --no-deps --force-recreate jiejing-ops-frontend || rollback_rc=1
    wait_container_healthy deploy-jiejing-ops-frontend-1 30 || rollback_rc=1
  else
    stop_candidate_ops_if_owned || rollback_rc=1
  fi
  "${previous_compose[@]}" up -d --no-deps --force-recreate jiejing-edge || rollback_rc=1
  wait_container_healthy deploy-jiejing-frontend-1 30 || rollback_rc=1
  wait_container_healthy deploy-jiejing-edge-1 30 || rollback_rc=1
  current_active="$(readlink -f -- "$ACTIVE_LINK" 2>/dev/null || true)"
  if [[ "$current_active" == "$candidate_app" ]]; then
    atomic_replace_active_link "$active_app" "$candidate_app" || rollback_rc=1
  else
    [[ "$current_active" == "$active_app" ]] || rollback_rc=1
  fi
  verify_previous_runtime_restored || rollback_rc=1
  wait_public_json "/health" 45 || rollback_rc=1
  wait_public_json "/health/deep" 45 || rollback_rc=1
  wait_public_json "/readiness/product-saas" 45 || rollback_rc=1
  if [[ "$rollback_rc" == "0" ]]; then
    printf '%s\n' 'APPLICATION_RELEASE_RESTORED=1'
  fi
  if [[ "${previous_ops_supported:-0}" == "1" ]]; then
    verify_ops_surface "$active_app" || rollback_rc=1
  else
    if ! ops_dns_points_to_old_host; then
      printf '%s\n' 'OPS_ROLLBACK_NEEDS_DNS_CUTBACK=1' >&2
    fi
    # DNS-only ops cannot establish where the proxied apex points. A prior
    # app-only release never receives an automatic full rollback proof.
    printf '%s\n' 'OPS_APEX_TRANSITION_ROLLBACK_REQUIRES_VERIFICATION=1' 'OPS_ROLLBACK_VERIFIED=0' >&2
    rollback_rc=1
  fi
  [[ "$rollback_rc" == "0" ]]
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

finalize_evidence_refresh_transaction() {
  current_stage="reacquire_maintenance_for_finalization"
  acquire_maintenance_lock || return 1
  current_stage="verify_final_runtime_image_coherence"
  verify_candidate_runtime_image_coherence || return 1
  current_stage="start_evidence_refresh_timer"
  start_and_verify_evidence_refresh_timer || return 1
  release_maintenance_lock || return 1
}

fail_unit_transaction() {
  local original_rc="${1:-1}" lock_rc=0 restore_rc=0 app_restore_rc=0 activity_restore_rc=0
  if [[ "$unit_transaction_failure_in_progress" == "1" ]]; then
    exit "$original_rc"
  fi
  trap '' HUP INT TERM
  unit_transaction_failure_in_progress=1
  unit_transaction_active=0
  trap - EXIT
  set +e
  printf 'JIEJING_PRODUCTION_UNIT_TRANSACTION_FAILED_STAGE=%s\n' "$current_stage" >&2
  acquire_maintenance_lock_for_rollback
  lock_rc=$?
  if [[ "$lock_rc" == "0" ]]; then
    restore_evidence_refresh_units
    restore_rc=$?
    rollback_application_release
    app_restore_rc=$?
  else
    restore_rc=1
    app_restore_rc=1
  fi
  release_maintenance_lock
  if [[ "$restore_rc" == "0" && "$app_restore_rc" == "0" ]]; then
    restore_evidence_refresh_timer_activity
    activity_restore_rc=$?
  else
    activity_restore_rc=1
  fi
  release_deploy_lock
  if [[ "$lock_rc" == "0" && "$restore_rc" == "0" ]]; then
    printf '%s\n' "TIMER_INSTALL_ROLLED_BACK=1" >&2
  fi
  if [[ "$app_restore_rc" == "0" ]]; then
    printf '%s\n' "APPLICATION_RELEASE_RETAINED=0" >&2
    printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1" >&2
  fi
  if [[ "$lock_rc" != "0" || "$restore_rc" != "0" || "$app_restore_rc" != "0" || "$activity_restore_rc" != "0" ]]; then
    printf '%s\n' "TIMER_INSTALL_ROLLBACK_INCOMPLETE=1" >&2
    printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_INCOMPLETE=1" >&2
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
  local code=$? rollback_rc=0
  trap - ERR
  disarm_unit_transaction_traps
  set +e
  printf 'JIEJING_PRODUCTION_DEPLOY_FAILED_STAGE=%s\n' "$current_stage" >&2
  if [[ "$mutation_started" == "1" ]]; then
    if acquire_maintenance_lock_for_rollback; then
      rollback_application_release || rollback_rc=1
    else
      rollback_rc=1
    fi
    if [[ "$rollback_rc" == "0" ]]; then
      printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1" >&2
    else
      printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_INCOMPLETE=1" >&2
    fi
  else
    printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_NOT_REQUIRED=1" >&2
  fi
  release_maintenance_lock
  release_deploy_lock
  exit "$code"
}
trap rollback_on_error ERR

current_stage="normalize_private_env_permissions"
if [[ "$private_env_normalization_required" == "1" ]]; then
  normalize_private_env_permissions
  private_env_normalization_applied=1
fi
printf 'PRIVATE_ENV_NORMALIZATION_APPLIED=%s\n' "$private_env_normalization_applied"

current_stage="capture_previous_runtime_images"
capture_previous_runtime_images

current_stage="build_candidate_images"
mutation_started=1
build_candidate_images_with_retry
current_stage="capture_candidate_runtime_images"
capture_candidate_runtime_images
current_stage="initialize_runtime_evidence_snapshot"
initialize_runtime_evidence_snapshot
current_stage="start_candidate_api"
"${candidate_compose[@]}" up -d --no-deps jiejing-saas
wait_container_healthy deploy-jiejing-saas-1 60
current_stage="start_candidate_worker"
"${candidate_compose[@]}" up -d --no-deps jiejing-worker
wait_container_healthy deploy-jiejing-worker-1 30
current_stage="verify_candidate_runtime_image_coherence"
verify_candidate_runtime_image_coherence
current_stage="start_candidate_frontend"
"${candidate_compose[@]}" up -d --no-deps --force-recreate jiejing-frontend
current_stage="start_candidate_ops_frontend"
"${candidate_compose[@]}" up -d --no-deps --force-recreate jiejing-ops-frontend
wait_container_healthy deploy-jiejing-ops-frontend-1 30
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
current_stage="verify_operations_tls_assets_and_anonymous_isolation"
verify_ops_surface "$candidate_app"
printf '%s\n' 'OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=1'
current_stage="activate_release"
arm_unit_transaction_traps
atomic_replace_active_link "$candidate_app" "$active_app"
active_switched=1

current_stage="install_evidence_refresh_units"
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

finalization_rc=0
finalize_evidence_refresh_transaction || finalization_rc=$?
if [[ "$finalization_rc" != "0" ]]; then
  fail_unit_transaction "$finalization_rc"
fi
printf '%s\n' "TIMER_INSTALL_APPLIED=1"
disarm_unit_transaction_traps
mutation_started=0
trap - ERR
release_deploy_lock

printf '%s\n' "JIEJING_PRODUCTION_DEPLOY_APPLIED=1"
printf '%s\n' "CANDIDATE_RELEASE_PERSISTED=1"
printf '%s\n' "ACTIVE_SWITCHED=1"
printf 'SOURCE_COMMIT=%s\n' "$SOURCE_SHA"
printf 'RELEASE_DIR=%s\n' "$release_dir"
printf 'PREVIOUS_RELEASE=%s\n' "$previous_release"
printf 'PRIVATE_DIR=%s\n' "$private_dir"
