#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${JIEJING_COMPOSE_FILE:-deploy/docker-compose.public-staging.yml}"
VAULT_SERVICE="${JIEJING_VAULT_SERVICE:-jiejing-vault}"
INIT_FILE="${JIEJING_VAULT_INIT_FILE:-/opt/jiejing-staging/private/vault-init.json}"
TOKEN_FILE="${JIEJING_VAULT_BACKEND_TOKEN_FILE:-/opt/jiejing-staging/private/vault-jiejing-saas-token.json}"
ENV_FILE="${JIEJING_VAULT_ENV_FILE:-deploy/jiejing-saas.staging-oauth.env}"
PATCH_ENV="${JIEJING_VAULT_PATCH_ENV:-false}"
KEYSPACE="${JIEJING_VAULT_KEYSPACE:-jiejing-staging}"

mkdir -p "$(dirname "$INIT_FILE")" "$(dirname "$TOKEN_FILE")"
chmod 700 "$(dirname "$INIT_FILE")" "$(dirname "$TOKEN_FILE")"

vault_exec() {
  docker compose -f "$COMPOSE_FILE" exec -T "$VAULT_SERVICE" sh -lc "VAULT_ADDR=http://127.0.0.1:8200 $*"
}

status_json() {
  vault_exec "vault status -format=json" 2>/dev/null || true
}

wait_seconds="${JIEJING_VAULT_READY_WAIT_SECONDS:-30}"
attempt=0
status=""
while [ "$attempt" -lt "$wait_seconds" ]; do
  status="$(status_json)"
  if [ -n "$status" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if [ -z "$status" ]; then
  echo "STAGING_VAULT_STATUS=blocked_not_ready" >&2
  exit 2
fi
initialized="$(printf '%s' "$status" | python3 -c "import json,sys; data=sys.stdin.read().strip(); print(str(json.loads(data).get('initialized', False)).lower() if data else 'false')")"

if [ "$initialized" = "false" ]; then
  vault_exec "vault operator init -key-shares=1 -key-threshold=1 -format=json" > "$INIT_FILE"
  chmod 600 "$INIT_FILE"
fi

unseal_key="$(python3 - "$INIT_FILE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
keys = data.get("unseal_keys_b64") or data.get("unseal_keys_hex") or []
if not keys:
    raise SystemExit("missing unseal key")
print(keys[0])
PY
)"

root_token="$(python3 - "$INIT_FILE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
token = data.get("root_token") or ""
if not token:
    raise SystemExit("missing root token")
print(token)
PY
)"

sealed="$(status_json | python3 -c "import json,sys; data=sys.stdin.read().strip(); print(str(json.loads(data).get('sealed', True)).lower() if data else 'true')")"
if [ "$sealed" = "true" ]; then
  vault_exec "vault operator unseal '$unseal_key' >/dev/null"
fi

vault_exec "VAULT_TOKEN='$root_token' vault secrets enable -path=secret kv-v2 >/dev/null 2>&1 || true"

policy_file="/tmp/jiejing-saas-policy.hcl"
cat > "$policy_file" <<EOF
path "secret/data/${KEYSPACE}/*" {
  capabilities = ["create", "update", "read", "delete"]
}

path "secret/metadata/${KEYSPACE}/*" {
  capabilities = ["list", "read", "delete"]
}
EOF

cat "$policy_file" | docker compose -f "$COMPOSE_FILE" exec -T "$VAULT_SERVICE" sh -lc "cat > /tmp/jiejing-saas-policy.hcl && VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN='$root_token' vault policy write jiejing-saas /tmp/jiejing-saas-policy.hcl >/dev/null"
rm -f "$policy_file"

docker compose -f "$COMPOSE_FILE" exec -T "$VAULT_SERVICE" sh -lc "VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN='$root_token' vault token create -policy=jiejing-saas -period=720h -format=json" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

backend_token="$(python3 - "$TOKEN_FILE" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)
token = ((data.get("auth") or {}).get("client_token")) or ""
if not token:
    raise SystemExit("missing backend token")
print(token)
PY
)"

if [ "$PATCH_ENV" = "true" ]; then
  python3 - "$ENV_FILE" "$backend_token" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
token = sys.argv[2]
text = path.read_text(encoding="utf-8") if path.exists() else ""
lines = text.splitlines()
updated = False
for index, line in enumerate(lines):
    if line.startswith("JIEJING_VAULT_TOKEN="):
        lines[index] = "JIEJING_VAULT_TOKEN=" + token
        updated = True
        break
if not updated:
    lines.append("JIEJING_VAULT_TOKEN=" + token)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  chmod 600 "$ENV_FILE"
fi

echo "STAGING_VAULT_STATUS=ready"
echo "STAGING_VAULT_INITIALIZED=true"
echo "STAGING_VAULT_UNSEALED=true"
echo "STAGING_VAULT_BACKEND_TOKEN_FILE=$TOKEN_FILE"
echo "STAGING_VAULT_ENV_PATCHED=$PATCH_ENV"
