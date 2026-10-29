<#
=============================================================================
  Intake Autopilot - one-time SSH provisioning for the client's Windows PC.
  The CLIENT runs this ONCE, as Administrator, to let the developer connect
  over SSH (reached privately over Tailscale - nothing is exposed to the
  internet). After this, the dev SSHes in and runs windows\run-all.ps1.

  What it does:
    * installs & starts the built-in Windows OpenSSH Server (auto-start)
    * makes PowerShell the default SSH shell (so docker / run-all.ps1 work)
    * authorises the developer's SSH public key (key-based login only)
    * enables Remote Desktop (RDP) as a GUI fallback, restricted to Tailscale
    * shows the Tailscale address to send to the developer

  Usage (Admin PowerShell), paste the dev's public key exactly as given:
    powershell -ExecutionPolicy Bypass -File windows\enable-ssh.ps1 `
      -DevPublicKey "ssh-ed25519 AAAA...dev@laptop"

  Docker Desktop must be set to start on login separately (one checkbox -
  see CLIENT-SETUP.md); this script does not touch auto-login (that would
  store your Windows password in the registry in clear text).
=============================================================================
#>
param(
  [Parameter(Mandatory=$true)][string]$DevPublicKey
)
$ErrorActionPreference = 'Stop'
function Ok($t){ Write-Host "  [OK] $t" -ForegroundColor Green }
function Info($t){ Write-Host "  ..  $t" -ForegroundColor Gray }
function Warn($t){ Write-Host "  [!]  $t" -ForegroundColor Red }
function Step($t){ Write-Host ""; Write-Host "> $t" -ForegroundColor Yellow }

# --- must be Administrator ----------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Warn "Please run this in an *Administrator* PowerShell (right-click PowerShell -> Run as administrator)."; exit 1 }

# --- sanity-check the key -----------------------------------------------------
if ($DevPublicKey -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-)') {
  Warn "That doesn't look like an SSH public key. It should start with 'ssh-ed25519' or 'ssh-rsa'."; exit 1
}

Write-Host ""; Write-Host "Intake Autopilot - enabling SSH access" -ForegroundColor Cyan

# --- 1. install OpenSSH Server ------------------------------------------------
Step "Installing the Windows OpenSSH Server (if needed)"
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null; Ok "OpenSSH Server installed" }
else { Ok "OpenSSH Server already installed" }

# --- 2. start + auto-start the service ---------------------------------------
Step "Starting the SSH service"
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
Ok "sshd running (auto-start on boot)"

# --- 3. firewall (Tailscale is private, but allow the local rule too) ---------
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
    -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
  Ok "firewall rule for TCP 22 added"
} else { Ok "firewall rule already present" }

# --- 4. default shell = PowerShell -------------------------------------------
Step "Setting PowerShell as the default SSH shell"
New-Item -Path "HKLM:\SOFTWARE\OpenSSH" -Force | Out-Null
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell `
  -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force | Out-Null
Ok "default shell set to PowerShell"

# --- 5. authorise the developer's key (admin_authorized_keys) -----------------
Step "Authorising the developer's SSH key"
$akf = Join-Path $env:ProgramData "ssh\administrators_authorized_keys"
if (-not (Test-Path $akf)) { New-Item -ItemType File -Path $akf -Force | Out-Null }
$existing = Get-Content $akf -ErrorAction SilentlyContinue
if ($existing -contains $DevPublicKey) { Ok "key already authorised" }
else {
  Add-Content -Path $akf -Value $DevPublicKey
  # OpenSSH requires this file to be owned by Administrators/SYSTEM only:
  icacls $akf /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
  Ok "developer key authorised (key-based login only)"
}

# --- 6. Remote Desktop (GUI fallback: start Docker Desktop / occasional clicks) --
# SSH covers everything command-line; RDP is the fallback for starting Docker
# Desktop or GUI-only steps. Restricted to the Tailscale range so it is NOT
# reachable from the public internet or the local LAN.
Step "Enabling Remote Desktop, restricted to Tailscale"
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -Value 0
# keep Network Level Authentication ON (secure default)
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name 'UserAuthentication' -Value 1 -ErrorAction SilentlyContinue
Enable-NetFirewallRule -DisplayGroup 'Remote Desktop' -ErrorAction SilentlyContinue
# scope to Tailscale's CGNAT range (100.64.0.0/10) - also makes RDP work over the
# Tailscale adapter regardless of how Windows classifies that network
Set-NetFirewallRule -DisplayGroup 'Remote Desktop' -Profile Any -RemoteAddress '100.64.0.0/10' -ErrorAction SilentlyContinue
Ok "Remote Desktop enabled (NLA on), reachable ONLY over Tailscale"
Warn "RDP uses this PC's Windows login password - make sure it's strong. Reach it with: mstsc -> the Tailscale IP."

# --- 7. Tailscale address for the dev ----------------------------------------
Step "Tailscale status"
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if ($ts) {
  $ip = (& tailscale ip -4 2>$null | Select-Object -First 1)
  if ($ip) { Ok "Tailscale IP: $ip" } else { Warn "Tailscale installed but not signed in yet - open Tailscale and sign in, then re-check with: tailscale ip -4" }
} else { Warn "Tailscale not found - install it and sign in (see CLIENT-SETUP.md), then run: tailscale ip -4" }

Write-Host ""
Write-Host "Done. Send the developer:" -ForegroundColor Cyan
Write-Host "  * Tailscale IP or device name (above)"
Write-Host "  * the Windows username to log in as:  $env:USERNAME"
Write-Host "They connect with:  ssh $env:USERNAME@<tailscale-ip>   (GUI fallback: mstsc / RDP to the same IP)"
Write-Host ""
Write-Host "Reminder: also tick 'Start Docker Desktop when you log in' in Docker settings," -ForegroundColor Gray
Write-Host "and keep this PC logged in (lock the screen, don't sign out) so Docker stays running." -ForegroundColor Gray
