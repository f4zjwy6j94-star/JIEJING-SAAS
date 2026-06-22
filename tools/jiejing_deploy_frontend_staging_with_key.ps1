param(
  [string]$Server = "43.129.205.244",
  [string]$User = "ubuntu",
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
$remoteScript = @"
set -euo pipefail
cd "$RemoteApp"
mkdir -p output/deploy-backups/$stamp
for path in app.js styles.css index.html app.html privacy.html terms.html risk-disclosure.html deploy/nginx.public-staging.conf; do
  if [ -f "$path" ]; then
    cp "$path" output/deploy-backups/$stamp/
  fi
done
mv /tmp/jiejing-app.js app.js
mv /tmp/jiejing-styles.css styles.css
mv /tmp/jiejing-index.html index.html
mv /tmp/jiejing-app.html app.html
mv /tmp/jiejing-privacy.html privacy.html
mv /tmp/jiejing-terms.html terms.html
mv /tmp/jiejing-risk-disclosure.html risk-disclosure.html
mv /tmp/jiejing-nginx.public-staging.conf deploy/nginx.public-staging.conf
if command -v node >/dev/null 2>&1; then
  node --check app.js
fi
python3 tools/jiejing_productization_stage_gate.py >/tmp/jiejing-stage-gate-$stamp.json
sudo -n docker compose -f deploy/docker-compose.public-https-staging.yml -p deploy up -d --no-deps --force-recreate jiejing-frontend
echo DEPLOY_FRONTEND_STATUS=ok
echo DEPLOY_FRONTEND_VERSION=20260521-ebay-oauth-callback-v11
"@

scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\app.js" "${target}:/tmp/jiejing-app.js"
scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\styles.css" "${target}:/tmp/jiejing-styles.css"
scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\index.html" "${target}:/tmp/jiejing-index.html"
scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\app.html" "${target}:/tmp/jiejing-app.html"
scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\privacy.html" "${target}:/tmp/jiejing-privacy.html"
scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\terms.html" "${target}:/tmp/jiejing-terms.html"
scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\risk-disclosure.html" "${target}:/tmp/jiejing-risk-disclosure.html"
scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 "$root\deploy\nginx.public-staging.conf" "${target}:/tmp/jiejing-nginx.public-staging.conf"
($remoteScript -replace "`r", "") | ssh -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 $target "bash -s"

