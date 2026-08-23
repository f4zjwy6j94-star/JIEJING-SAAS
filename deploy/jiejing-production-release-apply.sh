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
mutation_started=0

refuse() {
  printf '%s\n' "$1" >&2
  exit "${2:-1}"
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
release_dir="$RELEASE_ROOT/${STAMP}-${short_sha}"
candidate_app="$release_dir/app"
[[ ! -e "$release_dir" ]] || refuse "REFUSE_RELEASE_ALREADY_EXISTS=$release_dir" 29
install -d -m 0750 -o root -g root "$release_dir"
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
  printf 'CANDIDATE_RELEASE=%s\n' "$release_dir"
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
  local path="$1" marker="$2" attempts="${3:-45}" body
  for ((i=1; i<=attempts; i++)); do
    body="$(curl -fsS --max-time 10 -A 'Mozilla/5.0 JiejingProductionDeploy/1.0' "$PUBLIC_URL$path" 2>/dev/null || true)"
    [[ "$body" == *"$marker"* ]] && return 0
    sleep 2
  done
  return 1
}

rollback_on_error() {
  local code=$?
  trap - ERR
  set +e
  if [[ "$mutation_started" == "1" ]]; then
    "${previous_compose[@]}" build jiejing-saas jiejing-worker
    "${previous_compose[@]}" up -d --no-deps jiejing-saas
    wait_container_healthy deploy-jiejing-saas-1 60
    "${previous_compose[@]}" up -d --no-deps jiejing-worker
    "${previous_compose[@]}" up -d --no-deps --force-recreate jiejing-frontend
    "${previous_compose[@]}" up -d --no-deps --force-recreate jiejing-edge
    ln -sfnT "$active_app" "$ACTIVE_LINK"
    printf '%s\n' "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1" >&2
  fi
  exit "$code"
}
trap rollback_on_error ERR

mutation_started=1
"${candidate_compose[@]}" build jiejing-saas jiejing-worker
"${candidate_compose[@]}" up -d --no-deps jiejing-saas
wait_container_healthy deploy-jiejing-saas-1 60
"${candidate_compose[@]}" up -d --no-deps jiejing-worker
wait_container_healthy deploy-jiejing-worker-1 30
"${candidate_compose[@]}" up -d --no-deps --force-recreate jiejing-frontend
"${candidate_compose[@]}" up -d --no-deps --force-recreate jiejing-edge
wait_container_healthy deploy-jiejing-frontend-1 30
wait_container_healthy deploy-jiejing-edge-1 30
wait_public_json "/health" '"status":"ok"' 45
wait_public_json "/health/deep" '"status":"ready"' 45
wait_public_json "/readiness/product-saas" '"secret_exposed":false' 45
ln -sfnT "$candidate_app" "$ACTIVE_LINK"
mutation_started=0
trap - ERR

printf '%s\n' "JIEJING_PRODUCTION_DEPLOY_APPLIED=1"
printf 'SOURCE_COMMIT=%s\n' "$SOURCE_SHA"
printf 'RELEASE_DIR=%s\n' "$release_dir"
printf 'PREVIOUS_RELEASE=%s\n' "$previous_release"
printf 'PRIVATE_DIR=%s\n' "$private_dir"
