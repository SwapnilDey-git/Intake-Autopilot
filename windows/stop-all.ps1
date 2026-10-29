<#
=============================================================================
  Intake Autopilot - stop the system on Windows.
  Stops the reviewer dashboard (Node on :3000) and all Docker containers.
  Data is preserved (Postgres/n8n volumes + storage\ are untouched).
     powershell -ExecutionPolicy Bypass -File windows\stop-all.ps1
=============================================================================
#>
$ErrorActionPreference = 'Continue'
$Project = Split-Path -Parent $PSScriptRoot
Set-Location $Project

Write-Host "> Stopping the reviewer dashboard (port 3000)" -ForegroundColor Yellow
try {
  $conns = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
  Write-Host "  [OK] dashboard stopped (or was not running)" -ForegroundColor Green
} catch { Write-Host "  [!] could not stop dashboard automatically - close its window manually" -ForegroundColor Red }

Write-Host "> Stopping containers (docker compose stop)" -ForegroundColor Yellow
docker compose stop
Write-Host "  [OK] containers stopped. Data volumes preserved." -ForegroundColor Green
Write-Host ""
Write-Host "  Start again: powershell -File windows\run-all.ps1"
Write-Host "  Full reset (DELETES data): docker compose down -v"
