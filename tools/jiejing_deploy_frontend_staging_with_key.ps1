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
$remoteArchive = "/tmp/jiejing-frontend-patch-$stamp.tgz"

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
for path in app.js styles.css index.html app.html privacy.html terms.html risk-disclosure.html deploy/nginx.public-staging.conf; do
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
install -D -m 0644 "`$tmp_dir/deploy/nginx.public-staging.conf" deploy/nginx.public-staging.conf
python3 tools/jiejing_productization_stage_gate.py >/tmp/jiejing-stage-gate-$stamp.json
sudo -n docker compose -f deploy/docker-compose.public-https-staging.yml -p deploy up -d --no-deps --force-recreate jiejing-frontend
rm -rf "`$tmp_dir"
rm -f "$remoteArchive"
echo DEPLOY_FRONTEND_STATUS=ok
echo DEPLOY_BACKUP_DIR="`$backup_dir"
echo DEPLOY_FRONTEND_VERSION=20260628-billing-clarity-v13
"@

$archiveArgs = @("-czf", $patchArchive, "app.js", "styles.css", "index.html", "app.html", "privacy.html", "terms.html", "risk-disclosure.html", "deploy/nginx.public-staging.conf")
Invoke-NativeChecked "tar" $archiveArgs
$scpBaseArgs = @("-O", "-i", $KeyPath, "-P", [string]$Port, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
Invoke-NativeChecked "scp" ($scpBaseArgs + @($patchArchive, "${target}:$remoteArchive"))
$sshArgs = @("-i", $KeyPath, "-p", [string]$Port, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", $target, "bash -s")
($remoteScript -replace "`r", "") | & ssh @sshArgs
if ($LASTEXITCODE -ne 0) {
  throw "ssh failed with exit code $LASTEXITCODE"
}

