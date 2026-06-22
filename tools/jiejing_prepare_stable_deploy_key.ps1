param(
  [string]$Server = "43.129.205.244",
  [string]$User = "ubuntu",
  [string]$KeyName = "jiejing_route_a_edge_ed25519"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$keyDir = Join-Path $root "output\route-a-edge-ssh"
$keyPath = Join-Path $keyDir $KeyName
$pubPath = "$keyPath.pub"

New-Item -ItemType Directory -Path $keyDir -Force | Out-Null

if (-not (Test-Path -LiteralPath $keyPath)) {
  $escapedKeyPath = $keyPath.Replace('"', '\"')
  $command = "ssh-keygen -t ed25519 -N `"`" -C `"jiejing-staging-deploy`" -f `"$escapedKeyPath`""
  $process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $command) -Wait -PassThru -NoNewWindow
  if ($process.ExitCode -ne 0) {
    throw "ssh-keygen failed with exit code $($process.ExitCode)"
  }
}

$publicKey = Get-Content -LiteralPath $pubPath -Raw
$publicKey = $publicKey.Trim()
$quotedPublicKey = $publicKey.Replace("'", "'\''")

Write-Host "DEPLOY_KEY_PRIVATE=$keyPath"
Write-Host "DEPLOY_KEY_PUBLIC=$pubPath"
Write-Host ""
Write-Host "Run this once inside Tencent Cloud WebShell on the target server:"
Write-Host "export JIEJING_DEPLOY_PUBLIC_KEY='$quotedPublicKey'"
Write-Host "cd /opt/jiejing-staging/app && bash deploy/install-stable-deploy-key.sh"
Write-Host ""
Write-Host "After that, test from this machine:"
Write-Host "ssh -i `"$keyPath`" $User@$Server `"echo JIEJING_DEPLOY_KEY_OK`""
