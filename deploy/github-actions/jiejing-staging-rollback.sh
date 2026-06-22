#!/usr/bin/env bash
set -euo pipefail

# Manual rollback helper for the GitHub self-hosted runner deploy path. It
# restores only from backups created under /opt/jiejing-staging.

EXPECTED_CONFIRM="rollback app.jiejing.shop staging"
APP_DIR="${JIEJING_STAGING_APP_DIR:-/opt/jiejing-staging/app}"
DEPLOY_ROOT="${JIEJING_STAGING_DEPLOY_ROOT:-/opt/jiejing-staging}"
BACKUP_ROOT="${JIEJING_STAGING_BACKUP_ROOT:-$DEPLOY_ROOT/github-action-backups}"
ROLLBACK_BACKUP="${JIEJING_STAGING_ROLLBACK_BACKUP:-}"
DRY_RUN="${JIEJING_ROLLBACK_DRY_RUN:-1}"
CONFIRM="${JIEJING_STAGING_ROLLBACK_CONFIRM:-}"
RUN_ID="${GITHUB_RUN_ID:-manual}"
RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-1}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ "$CONFIRM" != "$EXPECTED_CONFIRM" ]]; then
  echo "REFUSE_ROLLBACK_CONFIRMATION_MISMATCH=1" >&2
  exit 22
fi

if [[ "$DRY_RUN" != "1" && "$DRY_RUN" != "0" ]]; then
  echo "REFUSE_INVALID_DRY_RUN=$DRY_RUN" >&2
  exit 23
fi

if [[ -z "$ROLLBACK_BACKUP" ]]; then
  echo "REFUSE_EMPTY_ROLLBACK_BACKUP=1" >&2
  exit 24
fi

resolved_app_dir="$(readlink -f -- "$APP_DIR" 2>/dev/null || true)"
resolved_backup_root="$(readlink -f -- "$BACKUP_ROOT" 2>/dev/null || true)"
if [[ -z "$resolved_app_dir" || -z "$resolved_backup_root" ]]; then
  echo "REFUSE_UNRESOLVED_ROLLBACK_PATH=1" >&2
  exit 25
fi

case "$resolved_app_dir" in
  /opt/jiejing-staging/app|/opt/jiejing-staging/app/*) ;;
  *) echo "REFUSE_APP_DIR_OUTSIDE_STAGING=$resolved_app_dir" >&2; exit 26 ;;
esac

case "$resolved_backup_root" in
  /opt/jiejing-staging/github-action-backups|/opt/jiejing-staging/github-action-backups/*) ;;
  *) echo "REFUSE_BACKUP_ROOT_OUTSIDE_STAGING=$resolved_backup_root" >&2; exit 27 ;;
esac

if [[ "$ROLLBACK_BACKUP" == /* ]]; then
  selected_backup="$(readlink -f -- "$ROLLBACK_BACKUP" 2>/dev/null || true)"
else
  selected_backup="$(readlink -f -- "$resolved_backup_root/$ROLLBACK_BACKUP" 2>/dev/null || true)"
fi

case "$selected_backup" in
  "$resolved_backup_root"/*) ;;
  *) echo "REFUSE_SELECTED_BACKUP_OUTSIDE_ROOT=$selected_backup" >&2; exit 28 ;;
esac

if [[ ! -d "$selected_backup/app" || ! -f "$selected_backup/app/app.js" ]]; then
  echo "REFUSE_SELECTED_BACKUP_INVALID=$selected_backup" >&2
  exit 29
fi

rollback_safety_backup="$resolved_backup_root/pre-rollback-${RUN_ID}-${RUN_ATTEMPT}-${STAMP}"
mkdir -p "$rollback_safety_backup/app"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "JIEJING_STAGING_ROLLBACK_DRY_RUN=1"
  echo "SELECTED_BACKUP=$selected_backup"
  echo "CURRENT_APP_BACKUP_WOULD_BE=$rollback_safety_backup"
  echo "ROLLBACK_APPLIED=0"
  exit 0
fi

rsync -a --delete "$resolved_app_dir/" "$rollback_safety_backup/app/"
rsync -a --delete "$selected_backup/app/" "$resolved_app_dir/"

cd "$resolved_app_dir"
COMPOSE_FILE="deploy/docker-compose.public-https-staging.yml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  COMPOSE_FILE="deploy/docker-compose.public-staging.yml"
fi
COMPOSE_ARGS=(-f "$COMPOSE_FILE")
COST_SAVER_OVERRIDE="${JIEJING_COST_SAVER_COMPOSE_OVERRIDE:-$resolved_app_dir/../private/docker-compose.cost-saver-local.yml}"
if [[ "${JIEJING_USE_COST_SAVER_OVERRIDE:-false}" == "true" && -f "$COST_SAVER_OVERRIDE" ]]; then
  COMPOSE_ARGS+=(-f "$COST_SAVER_OVERRIDE")
fi

docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps jiejing-saas
docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps jiejing-worker
docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-frontend

echo "JIEJING_STAGING_ROLLBACK_APPLIED=1"
echo "SELECTED_BACKUP=$selected_backup"
echo "CURRENT_APP_BACKUP=$rollback_safety_backup"
