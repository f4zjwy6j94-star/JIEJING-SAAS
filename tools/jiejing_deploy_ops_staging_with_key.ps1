param(
  [string]$Server = "43.129.205.244",
  [string]$User = "ubuntu",
  [int]$Port = 2222,
  [string]$KeyPath = "",
  [string]$KnownHostsPath = "",
  [string]$RemoteApp = "/opt/jiejing-staging/app"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
if (-not $KeyPath) {
  $KeyPath = Join-Path $root "output\route-a-edge-ssh\jiejing_route_a_edge_ed25519"
}
if (-not $KnownHostsPath) {
  $KnownHostsPath = Join-Path $root "output\deploy-keys\known_hosts"
}

foreach ($requiredPath in @($KeyPath, $KnownHostsPath)) {
  if (-not (Test-Path -LiteralPath $requiredPath)) {
    throw "Required SSH file not found: $requiredPath"
  }
}
if ($RemoteApp -notmatch '^/opt/[A-Za-z0-9._/-]+$') {
  throw "RemoteApp must be an explicit path below /opt"
}
if ($Server -notmatch '^[A-Za-z0-9.-]+$' -or $User -notmatch '^[A-Za-z0-9._-]+$') {
  throw "Unsafe SSH target"
}

$files = @(
  "ops.html",
  "ops.css",
  "ops.js",
  "assets/jiejing-ops-panels.js",
  "deploy/nginx.public-staging.conf"
)
foreach ($relativePath in $files) {
  if (-not (Test-Path -LiteralPath (Join-Path $root $relativePath))) {
    throw "Required ops artifact missing: $relativePath"
  }
}

function Invoke-NativeChecked {
  param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string[]]$Arguments
  )
  & $Executable @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Executable failed with exit code $LASTEXITCODE"
  }
}

Push-Location $root
try {
  Invoke-NativeChecked "node" @("--check", "ops.js")
  Invoke-NativeChecked "node" @("--check", "assets/jiejing-ops-panels.js")
  Invoke-NativeChecked "node" @("tools/codex_jiejing_merchant_ops_surface_isolation_smoke.js")
} finally {
  Pop-Location
}

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$localTemp = Join-Path $root "output\jiejing-ops-staging-$stamp"
$patchArchive = "$localTemp.tgz"
$remoteArchive = "/tmp/jiejing-ops-staging-$stamp.tgz"
$remoteScriptArchive = "/tmp/jiejing-ops-staging-$stamp.sh"
$remoteScriptPath = "$localTemp.sh"
$target = "$User@$Server"

$remoteTemplate = @'
set -Eeuo pipefail

APP_PATH="__REMOTE_APP__"
STAMP="__STAMP__"
ARCHIVE="__REMOTE_ARCHIVE__"
REMOTE_SCRIPT="__REMOTE_SCRIPT__"
COMPOSE_FILE="deploy/docker-compose.public-https-staging.yml"
BACKUP_DIR="$APP_PATH/output/deploy-backups/ops-$STAMP"
TMP_DIR=""
APPLIED=0
FILES=(
  "ops.html"
  "ops.css"
  "ops.js"
  "assets/jiejing-ops-panels.js"
  "deploy/nginx.public-staging.conf"
)

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf -- "$TMP_DIR"
  fi
  rm -f -- "$ARCHIVE" "$REMOTE_SCRIPT"
}

restore_previous() {
  local path
  for path in "${FILES[@]}"; do
    if [ -f "$BACKUP_DIR/$path" ]; then
      install -D -m 0644 "$BACKUP_DIR/$path" "$APP_PATH/$path"
    else
      rm -f -- "$APP_PATH/$path"
    fi
  done
  cd "$APP_PATH"
  sudo -n docker compose -f "$COMPOSE_FILE" -p deploy up -d --no-deps --force-recreate jiejing-frontend
  frontend_id=$(sudo -n docker compose -f "$COMPOSE_FILE" -p deploy ps -q jiejing-frontend)
  test -n "$frontend_id"
  sudo -n docker exec "$frontend_id" nginx -t
}

on_error() {
  rc=$?
  trap - ERR
  rollback_applied=0
  if [ "$APPLIED" = "1" ]; then
    if restore_previous; then
      rollback_applied=1
    fi
  fi
  cleanup
  printf 'DEPLOY_OPS_STATUS=failed\n'
  printf 'DEPLOY_OPS_ROLLBACK_APPLIED=%s\n' "$rollback_applied"
  exit "$rc"
}
trap on_error ERR

test -d "$APP_PATH"
available_kb=$(df -Pk "$APP_PATH" | awk 'NR==2 {print $4}')
test "${available_kb:-0}" -ge 131072

cd "$APP_PATH"
mkdir -p "$BACKUP_DIR"
for path in "${FILES[@]}"; do
  if [ -f "$path" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$path")"
    cp -p -- "$path" "$BACKUP_DIR/$path"
  fi
done

TMP_DIR=$(mktemp -d /tmp/jiejing-ops-staging-XXXXXX)
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
test "$(find "$TMP_DIR" -type f | wc -l | tr -d ' ')" = "5"
for path in "${FILES[@]}"; do
  test -f "$TMP_DIR/$path"
  test ! -L "$TMP_DIR/$path"
done

if command -v node >/dev/null 2>&1; then
  node --check "$TMP_DIR/ops.js"
  node --check "$TMP_DIR/assets/jiejing-ops-panels.js"
fi
grep -Fq 'jiejing-ops-panels.js' "$TMP_DIR/ops.html"
grep -Fq '20260828-ops-performance-v2' "$TMP_DIR/ops.html"
sudo -n docker run --rm --network deploy_default \
  --volume "$TMP_DIR/deploy/nginx.public-staging.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.27-alpine nginx -t

for path in "${FILES[@]}"; do
  install -D -m 0644 "$TMP_DIR/$path" "$APP_PATH/$path"
done
APPLIED=1

sudo -n docker compose -f "$COMPOSE_FILE" -p deploy up -d --no-deps --force-recreate jiejing-frontend
frontend_id=$(sudo -n docker compose -f "$COMPOSE_FILE" -p deploy ps -q jiejing-frontend)
test -n "$frontend_id"
sudo -n docker exec "$frontend_id" nginx -t

ops_body=$(curl -fsS -H 'Host: ops.jiejing.shop' http://127.0.0.1:18080/ops.html)
printf '%s' "$ops_body" | grep -Fq 'jiejing-ops-panels.js'
printf '%s' "$ops_body" | grep -Fq '20260828-ops-performance-v2'
curl -fsS -o /dev/null -H 'Host: ops.jiejing.shop' http://127.0.0.1:18080/assets/jiejing-ops-panels.js
app_ops_status=$(curl -sS -o /dev/null -w '%{http_code}' -H 'Host: app.jiejing.shop' http://127.0.0.1:18080/ops.html)
test "$app_ops_status" = "404"

trap - ERR
APPLIED=0
cleanup
printf 'DEPLOY_OPS_STATUS=ok\n'
printf 'DEPLOY_OPS_ROLLBACK_APPLIED=0\n'
printf 'DEPLOY_OPS_BACKUP_DIR=%s\n' "$BACKUP_DIR"
printf 'DEPLOY_OPS_FRONTEND_ID=%s\n' "$frontend_id"
'@

$remoteScript = $remoteTemplate.Replace("__REMOTE_APP__", $RemoteApp).Replace("__STAMP__", $stamp).Replace("__REMOTE_ARCHIVE__", $remoteArchive).Replace("__REMOTE_SCRIPT__", $remoteScriptArchive)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($remoteScriptPath, ($remoteScript -replace "`r", ""), $utf8NoBom)

try {
  Push-Location $root
  try {
    Invoke-NativeChecked "tar" (@("-czf", $patchArchive) + $files)
  } finally {
    Pop-Location
  }

  $sshSecurityArgs = @(
    "-i", $KeyPath,
    "-p", [string]$Port,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "UserKnownHostsFile=$KnownHostsPath"
  )
  $scpSecurityArgs = @(
    "-O",
    "-i", $KeyPath,
    "-P", [string]$Port,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "UserKnownHostsFile=$KnownHostsPath"
  )
  Invoke-NativeChecked "scp" ($scpSecurityArgs + @($patchArchive, "${target}:$remoteArchive"))
  Invoke-NativeChecked "scp" ($scpSecurityArgs + @($remoteScriptPath, "${target}:$remoteScriptArchive"))
  Invoke-NativeChecked "ssh" ($sshSecurityArgs + @($target, "bash $remoteScriptArchive"))
} finally {
  Remove-Item -LiteralPath $patchArchive -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $remoteScriptPath -ErrorAction SilentlyContinue
}
