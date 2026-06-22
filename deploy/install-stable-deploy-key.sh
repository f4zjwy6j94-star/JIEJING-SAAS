#!/usr/bin/env bash
set -euo pipefail

# Run once on the Tencent Cloud host through WebShell or an already approved SSH
# session. It installs a public deploy key so future code handoffs do not depend
# on repeated QR login challenges.

DEPLOY_HOME="${JIEJING_DEPLOY_HOME:-$HOME}"
PUBLIC_KEY="${JIEJING_DEPLOY_PUBLIC_KEY:-}"

if [[ -z "$PUBLIC_KEY" ]]; then
  echo "JIEJING_DEPLOY_PUBLIC_KEY is required." >&2
  echo "Example:" >&2
  echo "  JIEJING_DEPLOY_PUBLIC_KEY='ssh-ed25519 AAAA... jiejing-staging-deploy' bash deploy/install-stable-deploy-key.sh" >&2
  exit 1
fi

SSH_DIR="$DEPLOY_HOME/.ssh"
AUTHORIZED_KEYS="$SSH_DIR/authorized_keys"

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"
touch "$AUTHORIZED_KEYS"
chmod 600 "$AUTHORIZED_KEYS"

if grep -qxF "$PUBLIC_KEY" "$AUTHORIZED_KEYS"; then
  echo "DEPLOY_KEY_STATUS=already_installed"
else
  cp "$AUTHORIZED_KEYS" "$AUTHORIZED_KEYS.bak.$(date +%Y%m%d%H%M%S)"
  printf '%s\n' "$PUBLIC_KEY" >> "$AUTHORIZED_KEYS"
  echo "DEPLOY_KEY_STATUS=installed"
fi

echo "DEPLOY_HOME=$DEPLOY_HOME"
echo "AUTHORIZED_KEYS=$AUTHORIZED_KEYS"
echo "NEXT=Test from Windows: ssh -i output/deploy-keys/jiejing_staging_ed25519 <user>@<server-ip> 'echo ok'"
