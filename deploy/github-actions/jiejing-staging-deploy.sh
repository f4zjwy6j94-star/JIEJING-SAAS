#!/usr/bin/env bash
set -euo pipefail

# GitHub self-hosted runner entrypoint for JIEJING public staging deploys.
# It is intentionally manual, confirmation-gated, backup-first, and dry-run by
# default. Secrets stay on the server; this script does not print env contents.

EXPECTED_CONFIRM="deploy app.jiejing.shop staging"
APP_DIR="${JIEJING_STAGING_APP_DIR:-/opt/jiejing-staging/app}"
DEPLOY_ROOT="${JIEJING_STAGING_DEPLOY_ROOT:-/opt/jiejing-staging}"
BACKUP_ROOT="${JIEJING_STAGING_BACKUP_ROOT:-$DEPLOY_ROOT/github-action-backups}"
RELEASE_ROOT="${JIEJING_STAGING_RELEASE_ROOT:-$DEPLOY_ROOT/github-action-releases}"
DRY_RUN="${JIEJING_DEPLOY_DRY_RUN:-1}"
CONFIRM="${JIEJING_STAGING_DEPLOY_CONFIRM:-}"
WORKSPACE="${GITHUB_WORKSPACE:-$(pwd)}"
RUN_ID="${GITHUB_RUN_ID:-manual}"
RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-1}"
SHA="${GITHUB_SHA:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"

if [[ "$CONFIRM" != "$EXPECTED_CONFIRM" ]]; then
  echo "REFUSE_DEPLOY_CONFIRMATION_MISMATCH=1" >&2
  exit 12
fi

if [[ "$DRY_RUN" != "1" && "$DRY_RUN" != "0" ]]; then
  echo "REFUSE_INVALID_DRY_RUN=$DRY_RUN" >&2
  exit 13
fi

if [[ ! -d "$WORKSPACE" || ! -f "$WORKSPACE/app.js" || ! -f "$WORKSPACE/deploy/apply-staging-patch.sh" ]]; then
  echo "REFUSE_INVALID_GITHUB_WORKSPACE=$WORKSPACE" >&2
  exit 14
fi

resolved_app_dir="$(readlink -f -- "$APP_DIR" 2>/dev/null || true)"
resolved_deploy_root="$(readlink -f -- "$DEPLOY_ROOT" 2>/dev/null || true)"
if [[ -z "$resolved_app_dir" || -z "$resolved_deploy_root" ]]; then
  echo "REFUSE_UNRESOLVED_DEPLOY_PATH=1" >&2
  exit 15
fi

case "$resolved_app_dir" in
  /opt/jiejing-staging/app|/opt/jiejing-staging/app/*) ;;
  *) echo "REFUSE_APP_DIR_OUTSIDE_STAGING=$resolved_app_dir" >&2; exit 16 ;;
esac

case "$resolved_deploy_root" in
  /opt/jiejing-staging|/opt/jiejing-staging/*) ;;
  *) echo "REFUSE_DEPLOY_ROOT_OUTSIDE_STAGING=$resolved_deploy_root" >&2; exit 17 ;;
esac

short_sha="${SHA:0:12}"
if [[ -z "$short_sha" ]]; then
  short_sha="$(git -C "$WORKSPACE" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
fi

candidate_compose="$WORKSPACE/deploy/docker-compose.public-https-staging.yml"
if [[ ! -f "$candidate_compose" ]]; then
  candidate_compose="$WORKSPACE/deploy/docker-compose.public-staging.yml"
fi
runtime_compose="$resolved_app_dir/deploy/$(basename -- "$candidate_compose")"
private_dir="$resolved_deploy_root/private"
candidate_managed="$WORKSPACE/deploy/jiejing-saas.tencent-managed.env.example"
candidate_secret="$WORKSPACE/deploy/jiejing-saas.staging-oauth.env.example"
candidate_postgres="$WORKSPACE/deploy/jiejing-saas.postgres-localqueue.env.example"
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

if ! trusted_root_owned_path_chain_is_safe "$TRUSTED_RUNTIME_ENV_GUARD"; then
  echo "REFUSE_UNTRUSTED_RUNTIME_ENV_GUARD=1" >&2
  exit 22
fi
trusted_guard_resolved="$(readlink -f -- "$TRUSTED_RUNTIME_ENV_GUARD" 2>/dev/null || true)"
[[ "$trusted_guard_resolved" == "$TRUSTED_RUNTIME_ENV_GUARD" ]] || {
  echo "REFUSE_UNTRUSTED_RUNTIME_ENV_GUARD=1" >&2
  exit 22
}

if [[ "${JIEJING_USE_COST_SAVER_OVERRIDE:-false}" == "true" ]]; then
  cost_saver_override="${JIEJING_COST_SAVER_COMPOSE_OVERRIDE:-$private_dir/docker-compose.cost-saver-local.yml}"
  if [[ "$cost_saver_override" != "$private_dir/docker-compose.cost-saver-local.yml" ]] || \
    ! trusted_root_owned_path_chain_is_safe "$cost_saver_override"; then
    echo "REFUSE_UNTRUSTED_COST_SAVER_OVERRIDE=1" >&2
    exit 23
  fi
fi

run_dry_run_runtime_env_guard() {
  local candidate_compose_path="$1"
  local runtime_compose_path="$2"
  local override_args=()
  if [[ -n "$cost_saver_override" ]]; then
    override_args+=(--compose-override "$cost_saver_override")
  fi
  if [[ ! -f "$candidate_compose_path" || ! -f "$candidate_managed" || \
    ! -f "$candidate_secret" || ! -f "$candidate_postgres" ]]; then
    echo "REFUSE_RUNTIME_ENV_OWNERSHIP_GUARD=1" >&2
    exit 24
  fi
  if ! python3 "$TRUSTED_RUNTIME_ENV_GUARD" check \
    --compose "$candidate_compose_path" \
    --compose-runtime-path "$runtime_compose_path" \
    --managed-env "$candidate_managed" \
    --secret-env "$candidate_secret" \
    --postgres-env "$candidate_postgres" \
    --managed-runtime-path "$private_dir/tencent-managed.env" \
    --secret-runtime-path "$private_dir/jiejing-saas.staging-oauth.env" \
    --postgres-runtime-path "$private_dir/postgres-localqueue.env" \
    --required-runtime-service jiejing-saas \
    --required-runtime-service jiejing-worker \
    "${override_args[@]}"; then
    echo "REFUSE_RUNTIME_ENV_OWNERSHIP_GUARD=1" >&2
    exit 24
  fi
}

run_apply_runtime_env_guard() {
  local candidate_compose_path="$1"
  local runtime_compose_path="$2"
  local override_args=()
  if [[ -n "$cost_saver_override" ]]; then
    override_args+=(--compose-override "$cost_saver_override")
  fi
  if ! sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check \
    --compose "$candidate_compose_path" \
    --compose-runtime-path "$runtime_compose_path" \
    --managed-env "$private_dir/tencent-managed.env" \
    --secret-env "$private_dir/jiejing-saas.staging-oauth.env" \
    --postgres-env "$private_dir/postgres-localqueue.env" \
    --required-runtime-service jiejing-saas \
    --required-runtime-service jiejing-worker \
    "${override_args[@]}"; then
    echo "REFUSE_RUNTIME_ENV_OWNERSHIP_GUARD=1" >&2
    exit 24
  fi
}

run_runtime_env_guard() {
  if [[ "$DRY_RUN" == "1" ]]; then
    run_dry_run_runtime_env_guard "$candidate_compose" "$runtime_compose"
  else
    run_apply_runtime_env_guard "$candidate_compose" "$runtime_compose"
  fi
  echo "RUNTIME_ENV_GUARD_STATUS=passed"
}

run_runtime_env_guard

release_dir="$RELEASE_ROOT/github-${RUN_ID}-${RUN_ATTEMPT}-${short_sha}"
backup_dir="$BACKUP_ROOT/pre-github-${RUN_ID}-${RUN_ATTEMPT}-${STAMP}"
mkdir -p "$RELEASE_ROOT" "$BACKUP_ROOT"
rm -rf -- "$release_dir"
mkdir -p "$release_dir"

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
  --exclude 'id_*' \
  "$WORKSPACE/" "$release_dir/"

(
  cd "$release_dir"
  if [[ "$DRY_RUN" == "0" ]]; then
    python3 tools/jiejing_secret_scan.py
  fi
  node --check app.js
  python3 -m py_compile \
    jiejing_saas/api_server.py \
    jiejing_saas/readiness.py \
    jiejing_saas/config.py \
    jiejing_saas/security.py
)

{
  echo "RUN_ID=$RUN_ID"
  echo "RUN_ATTEMPT=$RUN_ATTEMPT"
  echo "SHA=$SHA"
  echo "SHORT_SHA=$short_sha"
  echo "STAMP=$STAMP"
  echo "DRY_RUN=$DRY_RUN"
  echo "APP_DIR=$resolved_app_dir"
  echo "RELEASE_DIR=$release_dir"
  echo "BACKUP_DIR=$backup_dir"
} > "$release_dir/JIEJING_GITHUB_ACTION_DEPLOY_MANIFEST.txt"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "JIEJING_STAGING_DEPLOY_DRY_RUN=1"
  echo "RELEASE_DIR=$release_dir"
  echo "BACKUP_DIR_WOULD_BE=$backup_dir"
  echo "PATCH_APPLIED=0"
  exit 0
fi

if [[ ! -d "$resolved_app_dir" || ! -f "$resolved_app_dir/app.js" ]]; then
  echo "REFUSE_CURRENT_APP_DIR_NOT_FOUND=$resolved_app_dir" >&2
  exit 18
fi

if [[ -z "${JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN:-}" ]]; then
  echo "REFUSE_MISSING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN=1" >&2
  exit 19
fi
printf '%s' "$JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN" | \
  sudo -n python3 "$release_dir/tools/jiejing_upsert_private_env_secret.py" \
    "$DEPLOY_ROOT/private/jiejing-saas.staging-oauth.env" \
    JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN
if [[ -z "${JIEJING_EBAY_CLIENT_SECRET:-}" ]]; then
  echo "REFUSE_MISSING_EBAY_CLIENT_SECRET=1" >&2
  exit 20
fi
printf '%s' "$JIEJING_EBAY_CLIENT_SECRET" | \
  sudo -n python3 "$release_dir/tools/jiejing_upsert_private_env_secret.py" \
    "$DEPLOY_ROOT/private/jiejing-saas.staging-oauth.env" \
    JIEJING_EBAY_CLIENT_SECRET
unset JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN JIEJING_EBAY_CLIENT_SECRET

NODE_BIN="$(command -v node)"
if [[ -z "$NODE_BIN" || ! -x "$NODE_BIN" ]]; then
  echo "REFUSE_MISSING_NODE_BIN=1" >&2
  exit 21
fi

mkdir -p "$backup_dir/app"
rsync -a --delete \
  --exclude '/output/private-backups/' \
  --exclude '/output/deploy-backups/' \
  --exclude '/output/staging-patch-backups/' \
  "$resolved_app_dir/" "$backup_dir/app/"

if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 8 http://127.0.0.1:8788/health > "$backup_dir/pre-deploy-health.json" || true
fi

sudo -n JIEJING_APP_DIR="$resolved_app_dir" JIEJING_NODE_BIN="$NODE_BIN" \
  bash "$release_dir/deploy/apply-staging-patch.sh" "$release_dir"

echo "JIEJING_STAGING_DEPLOY_APPLIED=1"
echo "RELEASE_DIR=$release_dir"
echo "BACKUP_DIR=$backup_dir"
