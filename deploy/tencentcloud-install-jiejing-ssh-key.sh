#!/usr/bin/env bash
set -euo pipefail

# Run once from Tencent Cloud OrcaTerm/web terminal as root. It installs the
# Codex staging public key for both root and a dedicated deploy user so future
# staging deploys can use non-interactive SSH instead of QR-gated login.

PUBLIC_KEY="${1:-ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB9QBXkgHWcuEG9vYdk8PV43fHjo5BV6dO0uDBKrHTOo jiejing-codex-staging-20260516}"
DEPLOY_USER="${JIEJING_DEPLOY_USER:-jiejing-deploy}"

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this bootstrap as root from Tencent Cloud web terminal." >&2
  exit 2
fi

install_key_for_user() {
  local user_name="$1"
  local home_dir
  home_dir="$(getent passwd "$user_name" | cut -d: -f6)"
  if [[ -z "$home_dir" || ! -d "$home_dir" ]]; then
    echo "Cannot find home directory for user: $user_name" >&2
    exit 3
  fi
  install -d -m 0700 -o "$user_name" -g "$user_name" "$home_dir/.ssh"
  touch "$home_dir/.ssh/authorized_keys"
  chown "$user_name:$user_name" "$home_dir/.ssh/authorized_keys"
  chmod 0600 "$home_dir/.ssh/authorized_keys"
  if ! grep -Fqx "$PUBLIC_KEY" "$home_dir/.ssh/authorized_keys"; then
    printf '%s\n' "$PUBLIC_KEY" >> "$home_dir/.ssh/authorized_keys"
  fi
}

if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$DEPLOY_USER"
fi

install_key_for_user root
install_key_for_user "$DEPLOY_USER"

if command -v usermod >/dev/null 2>&1 && getent group docker >/dev/null 2>&1; then
  usermod -aG docker "$DEPLOY_USER"
fi

cat >/etc/sudoers.d/jiejing-deploy <<EOF
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/docker, /usr/local/bin/docker, /usr/bin/docker-compose, /usr/local/bin/docker-compose, /bin/bash, /usr/bin/bash
EOF
chmod 0440 /etc/sudoers.d/jiejing-deploy

if grep -qE '^[#[:space:]]*PubkeyAuthentication' /etc/ssh/sshd_config; then
  sed -i 's/^[#[:space:]]*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
else
  printf '\nPubkeyAuthentication yes\n' >> /etc/ssh/sshd_config
fi

sshd -t
if command -v systemctl >/dev/null 2>&1; then
  systemctl reload sshd || systemctl reload ssh || true
else
  service sshd reload || service ssh reload || true
fi

echo "JIEJING_SSH_KEY_INSTALLED=1"
echo "DEPLOY_USER=$DEPLOY_USER"
