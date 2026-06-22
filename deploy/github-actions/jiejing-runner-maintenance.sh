#!/usr/bin/env bash
set -euo pipefail

# Manual maintenance helper for the Tencent Cloud GitHub self-hosted runner.
# It is dry-run by default and only archives old release-candidate directories
# created by the GitHub staging deploy workflow. It never touches the running
# app, backups, private env files, databases, Docker volumes, Vault material,
# eBay OAuth state, or billing/provider secrets.

EXPECTED_CONFIRM="cleanup app.jiejing.shop runner"
DEPLOY_ROOT="${JIEJING_STAGING_DEPLOY_ROOT:-/opt/jiejing-staging}"
RELEASE_ROOT="${JIEJING_STAGING_RELEASE_ROOT:-$DEPLOY_ROOT/github-action-releases}"
ARCHIVE_ROOT="${JIEJING_STAGING_RELEASE_ARCHIVE_ROOT:-$DEPLOY_ROOT/github-action-release-archives}"
DRY_RUN="${JIEJING_RUNNER_MAINTENANCE_DRY_RUN:-1}"
CONFIRM="${JIEJING_RUNNER_MAINTENANCE_CONFIRM:-}"
KEEP_LATEST="${JIEJING_RUNNER_MAINTENANCE_KEEP_LATEST:-5}"
ARCHIVE_AFTER_DAYS="${JIEJING_RUNNER_MAINTENANCE_ARCHIVE_AFTER_DAYS:-7}"
NOW_EPOCH="$(date -u +%s)"

if [[ "$CONFIRM" != "$EXPECTED_CONFIRM" ]]; then
  echo "REFUSE_MAINTENANCE_CONFIRMATION_MISMATCH=1" >&2
  exit 32
fi

if [[ "$DRY_RUN" != "1" && "$DRY_RUN" != "0" ]]; then
  echo "REFUSE_INVALID_MAINTENANCE_DRY_RUN=$DRY_RUN" >&2
  exit 33
fi

if [[ ! "$KEEP_LATEST" =~ ^[0-9]+$ || "$KEEP_LATEST" -lt 1 ]]; then
  echo "REFUSE_INVALID_KEEP_LATEST=$KEEP_LATEST" >&2
  exit 34
fi

if [[ ! "$ARCHIVE_AFTER_DAYS" =~ ^[0-9]+$ ]]; then
  echo "REFUSE_INVALID_ARCHIVE_AFTER_DAYS=$ARCHIVE_AFTER_DAYS" >&2
  exit 35
fi

resolved_release_root="$(readlink -f -- "$RELEASE_ROOT" 2>/dev/null || true)"
resolved_archive_root="$(readlink -m -- "$ARCHIVE_ROOT" 2>/dev/null || true)"

if [[ -z "$resolved_release_root" || ! -d "$resolved_release_root" ]]; then
  echo "REFUSE_RELEASE_ROOT_MISSING=$RELEASE_ROOT" >&2
  exit 36
fi

case "$resolved_release_root" in
  /opt/jiejing-staging/github-action-releases|/opt/jiejing-staging/github-action-releases/*) ;;
  *) echo "REFUSE_RELEASE_ROOT_OUTSIDE_STAGING=$resolved_release_root" >&2; exit 37 ;;
esac

case "$resolved_archive_root" in
  /opt/jiejing-staging/github-action-release-archives|/opt/jiejing-staging/github-action-release-archives/*) ;;
  *) echo "REFUSE_ARCHIVE_ROOT_OUTSIDE_STAGING=$resolved_archive_root" >&2; exit 38 ;;
esac

command -v tar >/dev/null 2>&1 || { echo "REFUSE_TAR_MISSING=1" >&2; exit 39; }

mapfile -t releases < <(find "$resolved_release_root" -mindepth 1 -maxdepth 1 -type d -name 'github-*' -printf '%T@ %p\n' | sort -rn)

archive_candidates=()
index=0
for row in "${releases[@]}"; do
  index=$((index + 1))
  release_path="${row#* }"
  resolved_release_path="$(readlink -f -- "$release_path" 2>/dev/null || true)"
  case "$resolved_release_path" in
    "$resolved_release_root"/github-*) ;;
    *) echo "REFUSE_RELEASE_CANDIDATE_OUTSIDE_ROOT=$resolved_release_path" >&2; exit 40 ;;
  esac

  if (( index <= KEEP_LATEST )); then
    continue
  fi

  modified_epoch="${row%% *}"
  modified_epoch="${modified_epoch%.*}"
  age_seconds=$((NOW_EPOCH - modified_epoch))
  age_days=$((age_seconds / 86400))
  if (( age_days >= ARCHIVE_AFTER_DAYS )); then
    archive_candidates+=("$resolved_release_path")
  fi
done

echo "JIEJING_RUNNER_MAINTENANCE_DRY_RUN=$DRY_RUN"
echo "RELEASE_ROOT=$resolved_release_root"
echo "ARCHIVE_ROOT=$resolved_archive_root"
echo "KEEP_LATEST=$KEEP_LATEST"
echo "ARCHIVE_AFTER_DAYS=$ARCHIVE_AFTER_DAYS"
echo "RELEASE_TOTAL=${#releases[@]}"
echo "ARCHIVE_CANDIDATE_COUNT=${#archive_candidates[@]}"

for candidate in "${archive_candidates[@]}"; do
  echo "ARCHIVE_CANDIDATE=$candidate"
done

if [[ "$DRY_RUN" == "1" ]]; then
  echo "ARCHIVE_APPLIED=0"
  echo "SECRET_EXPOSED=false"
  exit 0
fi

mkdir -p "$resolved_archive_root"

for candidate in "${archive_candidates[@]}"; do
  base="$(basename "$candidate")"
  archive_file="$resolved_archive_root/${base}.tar.gz"
  temp_archive="$resolved_archive_root/.${base}.tar.gz.tmp"

  if [[ -e "$archive_file" ]]; then
    echo "REFUSE_ARCHIVE_ALREADY_EXISTS=$archive_file" >&2
    exit 41
  fi

  tar -C "$resolved_release_root" -czf "$temp_archive" "$base"
  tar -tzf "$temp_archive" >/dev/null
  mv "$temp_archive" "$archive_file"

  # The release candidate is removed only after a readable tar archive exists.
  # This path is guarded above to stay inside github-action-releases/github-*.
  find "$candidate" -mindepth 1 -depth -delete
  rmdir "$candidate"
  echo "ARCHIVED_RELEASE=$candidate"
  echo "ARCHIVE_FILE=$archive_file"
done

echo "ARCHIVE_APPLIED=1"
echo "SECRET_EXPOSED=false"
