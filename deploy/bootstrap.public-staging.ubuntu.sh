#!/usr/bin/env bash
set -euo pipefail

# Minimal Ubuntu bootstrap for the first Jiejing public staging validation host.
# It prepares Docker Compose only. It does not create or print secrets.

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required on this bootstrap path." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release unzip

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get install -y docker.io docker-compose-plugin
fi

sudo systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is not available after install." >&2
  exit 1
fi

sudo mkdir -p /opt/jiejing-staging
sudo chown "$(id -u):$(id -g)" /opt/jiejing-staging

cat <<'NEXT_STEPS'
BOOTSTRAP_STATUS=ready

Next on the staging host:
1. Upload or unzip the Jiejing public staging bundle into /opt/jiejing-staging.
2. Create /opt/jiejing-staging/private/jiejing-saas.staging-oauth.env from deploy/jiejing-saas.staging-oauth.env.example.
3. Fill real staging, Vault and eBay OAuth values in that private env file; keep only the example file under deploy/.
4. Start the same-origin staging profile:

   cd /opt/jiejing-staging
   JIEJING_PUBLIC_HTTP_PORT=80 docker compose -f deploy/docker-compose.public-staging.yml up -d --build

5. Keep real platform writes disabled.
NEXT_STEPS
