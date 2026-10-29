<#
=============================================================================
  Intake Autopilot - FULL SYSTEM bring-up on Windows (Docker Desktop)
  Not a demo. This stands up the real running system end to end, the same
  operational sequence used on the Mac:
     stack up -> DB schema -> Ollama model -> n8n workflow import+activate ->
     dashboard -> health summary.

  Prereqs on the Windows box:
     * Docker Desktop running (Linux containers)
     * Node.js + npm (for the reviewer dashboard)
     * Internet on FIRST run only (to pull the vision model + build images)

  Usage (from anywhere; the script locates the project itself):
     powershell -ExecutionPolicy Bypass -File windows\run-all.ps1
     powershell -ExecutionPolicy Bypass -File windows\run-all.ps1 -Full
        -Full = import the full 3-channel workflow (only works if the Gmail
                OAuth credential already exists in n8n; otherwise it falls back
                to the webhook-active workflow and tells you).

  NOTE (Windows vs Mac): Windows runs Ollama in a container on CPU (model
  'minicpm-v'), so a form takes ~4-9 min. The Mac uses native Ollama on Metal.
=============================================================================
#>
param([switch]$Full)
$ErrorActionPreference = 'Continue'

$Project = Split-Path -Parent $PSScriptRoot
Set-Location $Project

function Banner($t){ Write-Host ""; Write-Host ("="*64) -ForegroundColor Cyan; Write-Host "  $t" -ForegroundColor Cyan; Write-Host ("="*64) -ForegroundColor Cyan }
function Step($t){ Write-Host ""; Write-Host "> $t" -ForegroundColor Yellow }
function Ok($t){ Write-Host "  [OK] $t" -ForegroundColor Green }
function Info($t){ Write-Host "  ..  $t" -ForegroundColor Gray }
function Warn($t){ Write-Host "  [!]  $t" -ForegroundColor Red }
function Sql($q){ (docker exec intake-db psql -U admin -d intake -t -A -c $q 2>$null | Out-String).Trim() }
function HttpCode($u){ try { return [int](Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 5).StatusCode } catch { return 0 } }
function WaitHttp($name,$u,$tries){ for($i=0;$i -lt $tries;$i++){ if((HttpCode $u) -eq 200){ Ok "$name ready"; return $true }; Start-Sleep 3 }; Warn "$name did not become ready ($u)"; return $false }

Banner "Intake Autopilot - full system bring-up (Windows)"

# --- 1. Docker ---------------------------------------------------------------
Step "Checking Docker"
docker info *> $null
if ($LASTEXITCODE -ne 0) { Warn "Docker Desktop is not running. Start it and re-run."; exit 1 }
Ok "Docker is running"

# --- 2. Bring up the stack (all 5 services incl. containerised Ollama) --------
Step "Building & starting containers (docker compose up -d --build)"
Info "First run also builds images and can take a few minutes."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Warn "docker compose failed - see output above."; exit 1 }
Ok "Containers started"

# --- 3. Postgres + schema ----------------------------------------------------
Step "Waiting for Postgres, then applying the schema"
for($i=0;$i -lt 40;$i++){ docker exec intake-db pg_isready -U admin -d intake *> $null; if($LASTEXITCODE -eq 0){break}; Start-Sleep 2 }
if ($LASTEXITCODE -ne 0) { Warn "Postgres not ready - check 'docker logs intake-db'."; exit 1 }
Ok "Postgres ready"
if (Test-Path "database\schema.sql") {
  Get-Content "database\schema.sql" -Raw | docker exec -i intake-db psql -U admin -d intake *> $null
  Ok "Schema applied (idempotent - safe to re-run)"
} else { Warn "database\schema.sql not found - skipping schema apply" }

# --- 4. Ollama model ---------------------------------------------------------
Step "Ensuring the vision model 'minicpm-v' is present (first run downloads it - can be slow)"
$have = (docker exec intake-ollama ollama list 2>$null | Out-String)
if ($have -match "minicpm-v") { Ok "model already pulled" }
else { Info "pulling minicpm-v ..."; docker exec intake-ollama ollama pull minicpm-v; if($LASTEXITCODE -eq 0){ Ok "model pulled" } else { Warn "model pull failed - ai-service will retry on first request" } }

# --- 5. Wait for app services ------------------------------------------------
Step "Waiting for services to answer"
WaitHttp "ai-service" "http://localhost:8000/docs" 40 | Out-Null
WaitHttp "n8n"        "http://localhost:5678/"     40 | Out-Null
WaitHttp "backend"    "http://localhost:8080/api/forms/pending" 40 | Out-Null

# --- 6. n8n: credential + workflow import + activate --------------------------
Step "Configuring the n8n intake workflow"
# 6a. Postgres credential (id must match the one the workflow references)
$hasPgCred = Sql "SELECT COUNT(*) FROM credentials_entity WHERE id='w4DRGMH6qN8WExUN';"
if ($hasPgCred -eq '0' -or $hasPgCred -eq '') {
  $cred = '[{"id":"w4DRGMH6qN8WExUN","name":"Postgres account","type":"postgres","data":{"host":"postgres","port":5432,"database":"intake","user":"admin","password":"password","ssl":"disable","sshTunnel":false}}]'
  $ct = Join-Path $env:TEMP "pgcred.json"; $cred | Set-Content $ct -Encoding ascii
  docker cp $ct intake-n8n:/tmp/cred.json | Out-Null
  docker exec intake-n8n n8n import:credentials --input=/tmp/cred.json *> $null
  docker exec intake-n8n sh -c "rm -f /tmp/cred.json" *> $null
  Remove-Item $ct -Force -ErrorAction SilentlyContinue
  Ok "Postgres credential imported"
} else { Ok "Postgres credential already present" }

# 6b. choose workflow: full (needs Gmail cred) or webhook-active fallback
$gmailCred = Sql "SELECT COUNT(*) FROM credentials_entity WHERE type='gmailOAuth2';"
if ($Full -and $gmailCred -ne '0' -and $gmailCred -ne '') {
  $wfFile = "n8n\Intake_Flow_full.json";    $channels = "webhook + email (Gmail); WhatsApp needs its header credential"
} else {
  if ($Full) { Warn "-Full requested but no Gmail credential in n8n yet -> using webhook-active workflow (see demo\GMAIL-SETUP.md to enable email)" }
  $wfFile = "n8n\Intake_Flow_webhook.json"; $channels = "webhook (email/WhatsApp need one-time credentials)"
}
$wfId = (Get-Content $wfFile -Raw | ConvertFrom-Json).id
Info "workflow: $wfFile  (id $wfId)"

# 6c. import if not already present
$exists = Sql "SELECT COUNT(*) FROM workflow_entity WHERE id='$wfId';"
if ($exists -eq '0' -or $exists -eq '') {
  docker cp $wfFile intake-n8n:/tmp/wf.json | Out-Null
  docker exec intake-n8n n8n import:workflow --input=/tmp/wf.json *> $null
  docker exec intake-n8n sh -c "rm -f /tmp/wf.json" *> $null
  Ok "workflow imported"
} else { Ok "workflow already imported" }

# 6d. exactly one active workflow owns the webhook path -> deactivate all, activate ours, restart
docker exec intake-n8n n8n update:workflow --all --active=false *> $null
docker exec intake-n8n n8n update:workflow --active=true --id=$wfId *> $null
Info "restarting n8n so it registers the webhook at boot"
docker restart intake-n8n *> $null
WaitHttp "n8n (post-restart)" "http://localhost:5678/" 40 | Out-Null

$hook = Sql "SELECT ""webhookPath"" FROM webhook_entity WHERE ""webhookPath""='upload-real';"
if ($hook -eq 'upload-real') { Ok "intake webhook registered: POST http://localhost:5678/webhook/upload-real" }
else { Warn "webhook not registered - check 'docker logs intake-n8n'" }

# --- 7. Dashboard ------------------------------------------------------------
Step "Starting the reviewer dashboard"
if (Test-Path "dashboard\package.json") {
  if (-not (Test-Path "dashboard\node_modules")) { Info "installing dashboard dependencies (first run)"; Push-Location dashboard; npm install; Pop-Location }
  if ((HttpCode "http://localhost:3000") -eq 200) { Ok "dashboard already running (http://localhost:3000)" }
  else {
    Start-Process powershell -ArgumentList '-NoExit','-Command','npm run dev' -WorkingDirectory (Join-Path $Project 'dashboard') | Out-Null
    if (WaitHttp "dashboard" "http://localhost:3000" 30) { } else { Info "dashboard still starting - it will come up in its own window" }
  }
} else { Warn "dashboard\ not found - skipping" }

# --- 8. Summary --------------------------------------------------------------
Banner "System is up"
Write-Host "  Dashboard (reviewer UI) : http://localhost:3000"
Write-Host "  Backend API             : http://localhost:8080"
Write-Host "  ai-service (docs)       : http://localhost:8000/docs"
Write-Host "  n8n editor              : http://localhost:5678"
Write-Host "  Intake webhook (live)   : POST http://localhost:5678/webhook/upload-real"
Write-Host ""
Write-Host "  Active channels: $channels" -ForegroundColor Green
Write-Host ""
Write-Host "  Send a form through the pipeline (CPU inference ~4-9 min):"
Write-Host '     curl.exe -X POST --data-binary "@testdoc\Test Doc 2.pdf" -H "Content-Type: application/pdf" http://localhost:5678/webhook/upload-real' -ForegroundColor Gray
Write-Host "  Then review & approve it in the dashboard."
Write-Host ""
Write-Host "  Enable the EMAIL channel later: follow demo\GMAIL-SETUP.md, then re-run this with -Full."
Write-Host "  Stop everything: powershell -File windows\stop-all.ps1"
Write-Host ""
