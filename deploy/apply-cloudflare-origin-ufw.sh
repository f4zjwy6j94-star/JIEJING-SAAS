#!/usr/bin/env bash
set -euo pipefail

# Lock Jiejing's origin web ports so public traffic must pass through
# Cloudflare. Keep SSH available for operator recovery.

CF_IPV4_URL="${CF_IPV4_URL:-https://www.cloudflare.com/ips-v4}"
CF_IPV6_URL="${CF_IPV6_URL:-https://www.cloudflare.com/ips-v6}"
WEB_PORTS="${JIEJING_WEB_PORTS:-80 443}"
SSH_PORTS="${JIEJING_SSH_PORTS:-22 2222}"
BACKUP_DIR="${JIEJING_UFW_BACKUP_DIR:-/var/backups/jiejing-origin-lock}"

if ! command -v ufw >/dev/null 2>&1; then
  echo "ufw is required on the origin host" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

curl -fsSL "$CF_IPV4_URL" -o "$tmp_dir/cloudflare-ips-v4.txt"
curl -fsSL "$CF_IPV6_URL" -o "$tmp_dir/cloudflare-ips-v6.txt"

sudo -n mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
sudo -n ufw status numbered > "$tmp_dir/status-before.txt" || true
sudo -n install -m 0644 "$tmp_dir/status-before.txt" "$BACKUP_DIR/status-before-$timestamp.txt"

sudo -n ufw default deny incoming
sudo -n ufw default allow outgoing

existing_direct_web_denies="$(
  sudo -n ufw status numbered |
    awk '/Jiejing deny direct origin web/ {gsub(/\[|\]/, "", $1); print $1}' |
    sort -rn
)"
for rule_no in $existing_direct_web_denies; do
  sudo -n ufw --force delete "$rule_no" >/dev/null
done

for port in $SSH_PORTS; do
  sudo -n ufw limit "$port/tcp" comment "Jiejing SSH operator access $port"
done

while IFS= read -r cidr || [[ -n "$cidr" ]]; do
  [[ -z "$cidr" ]] && continue
  [[ "$cidr" =~ ^[0-9./]+$ ]] || {
    echo "Unexpected Cloudflare IPv4 range: $cidr" >&2
    exit 1
  }
  for port in $WEB_PORTS; do
    sudo -n ufw allow proto tcp from "$cidr" to any port "$port" comment "Jiejing Cloudflare web $port"
  done
done < "$tmp_dir/cloudflare-ips-v4.txt"

if grep -qi '^IPV6=yes' /etc/default/ufw 2>/dev/null; then
  while IFS= read -r cidr || [[ -n "$cidr" ]]; do
    [[ -z "$cidr" ]] && continue
    [[ "$cidr" =~ ^[0-9a-fA-F:./]+$ ]] || {
      echo "Unexpected Cloudflare IPv6 range: $cidr" >&2
      exit 1
    }
    for port in $WEB_PORTS; do
      sudo -n ufw allow proto tcp from "$cidr" to any port "$port" comment "Jiejing Cloudflare web $port"
    done
  done < "$tmp_dir/cloudflare-ips-v6.txt"
fi

for port in $WEB_PORTS; do
  sudo -n ufw deny "$port/tcp" comment "Jiejing deny direct origin web $port"
done

sudo -n ufw --force enable
sudo -n ufw status verbose
