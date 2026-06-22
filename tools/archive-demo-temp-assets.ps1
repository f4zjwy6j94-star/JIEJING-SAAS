param(
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

$demoRoot = Split-Path -Parent $PSScriptRoot
$archiveRoot = Join-Path $demoRoot "artifacts\archive\tmp-screenshots-$(Get-Date -Format yyyyMMdd-HHmmss)"

$patterns = @("tmp*.png", ".tmp*.png")
$files = @()
foreach ($pattern in $patterns) {
  $files += Get-ChildItem -Path $demoRoot -File -Force -Filter $pattern -ErrorAction SilentlyContinue
}

$files = $files | Sort-Object FullName -Unique
$totalBytes = ($files | Measure-Object Length -Sum).Sum

[PSCustomObject]@{
  Mode = $(if ($Apply) { "APPLY" } else { "DRY_RUN" })
  DemoRoot = $demoRoot
  ArchiveRoot = $archiveRoot
  FileCount = $files.Count
  TotalMB = [math]::Round(($totalBytes / 1MB), 2)
} | Format-List

if ($files.Count -eq 0) {
  Write-Output "No root-level tmp PNG files found."
  exit 0
}

$files | Select-Object Name, @{n="MB";e={[math]::Round($_.Length / 1MB, 2)}}, LastWriteTime |
  Format-Table -AutoSize

if (-not $Apply) {
  Write-Output ""
  Write-Output "Dry run only. Re-run with -Apply to archive these files."
  exit 0
}

New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null

foreach ($file in $files) {
  Move-Item -LiteralPath $file.FullName -Destination (Join-Path $archiveRoot $file.Name)
}

Write-Output ""
Write-Output "Archived $($files.Count) files to $archiveRoot"
