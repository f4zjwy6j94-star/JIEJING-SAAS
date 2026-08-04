#!/usr/bin/env bash
set -euo pipefail

# Ubuntu bootstrap for the Jiejing public staging host. It installs Docker,
# initializes three private runtime env files from public templates without
# overwriting existing values, and runs value-free ownership checks when the
# application bundle is already present. It never sources or prints env files.

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required on this bootstrap path." >&2
  exit 1
fi

DEPLOY_ROOT="${JIEJING_STAGING_DEPLOY_ROOT:-/opt/jiejing-staging}"
APP_DIR="${JIEJING_STAGING_APP_DIR:-$DEPLOY_ROOT/app}"
PRIVATE_DIR="$DEPLOY_ROOT/private"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
OWNER_UID="$(id -u)"
OWNER_GID="$(id -g)"
TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"

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
  exit 2
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release python3 unzip

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get install -y docker.io docker-compose-plugin
fi

sudo systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is not available after install." >&2
  exit 1
fi

sudo install -d -m 0755 -o "$OWNER_UID" -g "$OWNER_GID" "$DEPLOY_ROOT" "$APP_DIR"
if sudo test -L "$PRIVATE_DIR"; then
  echo "Refusing symlink private env directory." >&2
  exit 1
fi
sudo install -d -m 0700 -o "$OWNER_UID" -g "$OWNER_GID" "$PRIVATE_DIR"

install_private_env() {
  local template_name="$1"
  local private_name="$2"
  local template_path="$SOURCE_ROOT/deploy/$template_name"
  local private_path="$PRIVATE_DIR/$private_name"

  if [[ ! -f "$template_path" ]]; then
    echo "Missing public env template: $template_name" >&2
    exit 1
  fi
  if sudo test -L "$private_path"; then
    echo "Refusing symlink private env target: $private_name" >&2
    exit 1
  fi
  if ! sudo test -e "$private_path"; then
    sudo install -m 0600 -o "$OWNER_UID" -g "$OWNER_GID" "$template_path" "$private_path"
  fi
  if ! sudo test -f "$private_path"; then
    echo "Private env target is not a regular file: $private_name" >&2
    exit 1
  fi
  sudo chmod 0600 "$private_path"
  if [[ "$(sudo stat -c '%a' "$private_path")" != "600" ]]; then
    echo "Private env permissions are not 0600: $private_name" >&2
    exit 1
  fi
}

install_private_env "jiejing-saas.tencent-managed.env.example" "tencent-managed.env"
install_private_env "jiejing-saas.staging-oauth.env.example" "jiejing-saas.staging-oauth.env"
install_private_env "jiejing-saas.postgres-localqueue.env.example" "postgres-localqueue.env"

run_runtime_env_guard() {
  local compose="$APP_DIR/deploy/docker-compose.public-staging.yml"
  local cost_saver_override=""
  local override_args=()
  if [[ ! -f "$compose" ]]; then
    echo "RUNTIME_ENV_GUARD_STATUS=pending_bundle_in_app"
    return 0
  fi
  if [[ "${JIEJING_USE_COST_SAVER_OVERRIDE:-false}" == "true" ]]; then
    cost_saver_override="${JIEJING_COST_SAVER_COMPOSE_OVERRIDE:-$PRIVATE_DIR/docker-compose.cost-saver-local.yml}"
    if [[ "$cost_saver_override" != "$PRIVATE_DIR/docker-compose.cost-saver-local.yml" ]] || \
      ! trusted_root_owned_path_chain_is_safe "$cost_saver_override"; then
      echo "REFUSE_UNTRUSTED_COST_SAVER_OVERRIDE=1" >&2
      exit 3
    fi
    override_args+=(--compose-override "$cost_saver_override")
  fi

  sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check \
    --compose "$compose" \
    --managed-env "$PRIVATE_DIR/tencent-managed.env" \
    --secret-env "$PRIVATE_DIR/jiejing-saas.staging-oauth.env" \
    --postgres-env "$PRIVATE_DIR/postgres-localqueue.env" \
    "${override_args[@]}" \
    --json
  sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" migrate \
    --compose "$compose" \
    --managed-env "$PRIVATE_DIR/tencent-managed.env" \
    --secret-env "$PRIVATE_DIR/jiejing-saas.staging-oauth.env" \
    --postgres-env "$PRIVATE_DIR/postgres-localqueue.env" \
    "${override_args[@]}" \
    --json
  echo "RUNTIME_ENV_GUARD_STATUS=check_and_dry_run_passed"
}

run_runtime_env_guard

cat <<'NEXT_STEPS'
BOOTSTRAP_STATUS=ready

Next on the staging host:
1. Upload or unzip the Jiejing public staging bundle into /opt/jiejing-staging/app.
2. Rerun this bootstrap from that app tree. It preserves existing private env
   files, verifies mode 0600, then runs ownership check and migration dry-run.
3. Fill placeholders through the backend-only operator path. Never print, source,
   or copy private values back into deploy/.
4. Confirm the canonical managed -> secret -> postgres order, then start staging:

   cd /opt/jiejing-staging/app
   JIEJING_PUBLIC_HTTP_PORT=80 docker compose -f deploy/docker-compose.public-staging.yml up -d --build

5. Keep real platform writes and public charging disabled.
NEXT_STEPS
