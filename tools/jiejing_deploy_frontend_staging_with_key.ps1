param(
  [string]$Server = "43.129.205.244",
  [string]$User = "ubuntu",
  [int]$Port = 2222,
  [string]$KeyPath = "",
  [string]$RemoteApp = "/opt/jiejing-staging/app"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
if (-not $KeyPath) {
  $KeyPath = Join-Path $root "output\route-a-edge-ssh\jiejing_route_a_edge_ed25519"
}

if (-not (Test-Path -LiteralPath $KeyPath)) {
  throw "Deploy key not found: $KeyPath. Run tools\jiejing_prepare_stable_deploy_key.ps1 first."
}

$target = "$User@$Server"
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$patchArchive = Join-Path $root "output\jiejing-frontend-patch-$stamp.tgz"
$remoteScriptPath = Join-Path $root "output\jiejing-frontend-remote-$stamp.sh"
$remoteArchive = "/tmp/jiejing-frontend-patch-$stamp.tgz"
$remoteScriptArchive = "/tmp/jiejing-frontend-remote-$stamp.sh"
$appHtml = Get-Content -LiteralPath (Join-Path $root "app.html") -Raw -Encoding UTF8
if ($appHtml -notmatch 'app\.js\?v=([^"''>]+)') {
  throw "Unable to derive frontend asset version from app.html"
}
$frontendVersion = $Matches[1]

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

$remoteScript = @"
set -euo pipefail
cd "$RemoteApp"
backup_dir="output/deploy-backups/$stamp"
mkdir -p "`$backup_dir/deploy"
for path in app.js styles.css index.html app.html privacy.html terms.html risk-disclosure.html favicon.ico assets/jiejing-app-icon.svg assets/jiejing-logo-lockup.svg assets/jiejing-logo-mark.svg deploy/nginx.public-staging.conf deploy/Caddyfile.public-staging.systemd; do
  if [ -f "$path" ]; then
    mkdir -p "`$backup_dir/`$(dirname "`$path")"
    cp "$path" "`$backup_dir/$path"
  fi
done
tmp_dir=`$(mktemp -d /tmp/jiejing-frontend-patch-XXXXXX)
tar -xzf "$remoteArchive" -C "`$tmp_dir"
if command -v node >/dev/null 2>&1; then
  node --check "`$tmp_dir/app.js"
fi
install -m 0644 "`$tmp_dir/app.js" app.js
install -m 0644 "`$tmp_dir/styles.css" styles.css
install -m 0644 "`$tmp_dir/index.html" index.html
install -m 0644 "`$tmp_dir/app.html" app.html
install -m 0644 "`$tmp_dir/privacy.html" privacy.html
install -m 0644 "`$tmp_dir/terms.html" terms.html
install -m 0644 "`$tmp_dir/risk-disclosure.html" risk-disclosure.html
install -m 0644 "`$tmp_dir/favicon.ico" favicon.ico
install -D -m 0644 "`$tmp_dir/assets/jiejing-app-icon.svg" assets/jiejing-app-icon.svg
install -D -m 0644 "`$tmp_dir/assets/jiejing-logo-lockup.svg" assets/jiejing-logo-lockup.svg
install -D -m 0644 "`$tmp_dir/assets/jiejing-logo-mark.svg" assets/jiejing-logo-mark.svg
install -D -m 0644 "`$tmp_dir/deploy/nginx.public-staging.conf" deploy/nginx.public-staging.conf
install -D -m 0644 "`$tmp_dir/deploy/Caddyfile.public-staging.systemd" deploy/Caddyfile.public-staging.systemd
if command -v caddy >/dev/null 2>&1; then
  caddy validate --config deploy/Caddyfile.public-staging.systemd
fi
if command -v systemctl >/dev/null 2>&1 && sudo -n test -d /etc/caddy; then
  sudo -n install -m 0644 deploy/Caddyfile.public-staging.systemd /etc/caddy/Caddyfile
  if sudo -n systemctl is-active --quiet caddy; then
    sudo -n systemctl reload caddy
  fi
fi
python3 tools/jiejing_productization_stage_gate.py >/tmp/jiejing-stage-gate-$stamp.json
sudo -n docker compose -f deploy/docker-compose.public-https-staging.yml -p deploy up -d --no-deps --force-recreate jiejing-frontend
rm -rf "`$tmp_dir"
rm -f "$remoteArchive" "$remoteScriptArchive"
echo DEPLOY_FRONTEND_STATUS=ok
echo DEPLOY_BACKUP_DIR="`$backup_dir"
echo DEPLOY_FRONTEND_VERSION=$frontendVersion
"@

$archiveArgs = @("-czf", $patchArchive, "app.js", "styles.css", "index.html", "app.html", "privacy.html", "terms.html", "risk-disclosure.html", "favicon.ico", "assets/jiejing-app-icon.svg", "assets/jiejing-logo-lockup.svg", "assets/jiejing-logo-mark.svg", "deploy/nginx.public-staging.conf", "deploy/Caddyfile.public-staging.systemd")
Invoke-NativeChecked "tar" $archiveArgs
$remoteScriptForSsh = $remoteScript.TrimStart([char]0xFEFF) -replace "`r", ""
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($remoteScriptPath, $remoteScriptForSsh, $utf8NoBom)
$scpBaseArgs = @("-O", "-i", $KeyPath, "-P", [string]$Port, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
Invoke-NativeChecked "scp" ($scpBaseArgs + @($patchArchive, "${target}:$remoteArchive"))
Invoke-NativeChecked "scp" ($scpBaseArgs + @($remoteScriptPath, "${target}:$remoteScriptArchive"))
$sshArgs = @("-i", $KeyPath, "-p", [string]$Port, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", $target, "bash $remoteScriptArchive")
& ssh @sshArgs
if ($LASTEXITCODE -ne 0) {
  throw "ssh failed with exit code $LASTEXITCODE"
}
Remove-Item -LiteralPath $remoteScriptPath -ErrorAction SilentlyContinue
