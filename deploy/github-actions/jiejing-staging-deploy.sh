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
  python3 tools/jiejing_secret_scan.py
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

mkdir -p "$backup_dir/app"
rsync -a --delete \
  --exclude '/output/private-backups/' \
  --exclude '/output/deploy-backups/' \
  --exclude '/output/staging-patch-backups/' \
  "$resolved_app_dir/" "$backup_dir/app/"

if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 8 http://127.0.0.1:8788/health > "$backup_dir/pre-deploy-health.json" || true
fi

sudo -n JIEJING_APP_DIR="$resolved_app_dir" bash "$release_dir/deploy/apply-staging-patch.sh" "$release_dir"

echo "JIEJING_STAGING_DEPLOY_APPLIED=1"
echo "RELEASE_DIR=$release_dir"
echo "BACKUP_DIR=$backup_dir"
