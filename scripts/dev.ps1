<#
  Start the WhisperText dev environment so it survives the terminal that
  launched it.

  The Python backend and the Vite dev server are started DETACHED in the
  background (logs go to .dev\), and Electron is launched detached too. Closing
  this terminal — or quitting the app — leaves the servers running, so the
  overlay and settings windows keep working next time you open the app.

  Re-running is safe and idempotent: anything already up on its port is left
  alone, so this doubles as a "make sure everything's running" command. Pass
  -Restart to stop the background servers first and start clean.

  Run from anywhere:  .\scripts\dev.ps1   (or  .\scripts\dev.ps1 -Restart)
  Stop the servers:   .\scripts\dev-stop.ps1
#>
[CmdletBinding()]
param([switch]$Restart)

$ErrorActionPreference = "Stop"
$root   = (Resolve-Path "$PSScriptRoot\..").Path
$fe     = Join-Path $root "frontend"
$devDir = Join-Path $root ".dev"
New-Item -ItemType Directory -Force -Path $devDir | Out-Null

$BACKEND_PORT = 43117
$VITE_PORT    = 5173

# --------------------------------------------------------------------- helpers
# Readiness is tested over HTTP, not by scanning ports. Vite binds to the IPv6
# loopback ([::1]) only, which "localhost" resolves to but "127.0.0.1" does not
# — and this machine's Get-NetTCPConnection (CIM-backed) is unreliable, so a
# port scan can wrongly report a healthy server as down.
function Wait-For([scriptblock]$Condition, [int]$TimeoutSec, [string]$What) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    if (& $Condition) { return $true }
    Start-Sleep -Milliseconds 350
  }
  Write-Warning "Timed out waiting for $What."
  return $false
}

function Backend-Healthy {
  try { return (Invoke-RestMethod "http://127.0.0.1:$BACKEND_PORT/health" -TimeoutSec 2).status -eq "ok" }
  catch { return $false }
}

function Vite-Up {
  try { Invoke-WebRequest "http://localhost:$VITE_PORT/" -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true }
  catch { return $false }
}

# Launch a process that keeps running after this terminal closes, with its
# output captured to log files, and record its PID so dev-stop can find it.
function Start-Detached([string]$Name, [string]$FilePath, [string[]]$ArgList, [string]$WorkDir) {
  $out = Join-Path $devDir "$Name.out.log"
  $err = Join-Path $devDir "$Name.err.log"
  $p = Start-Process -FilePath $FilePath -ArgumentList $ArgList -WorkingDirectory $WorkDir `
         -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
  Set-Content -Path (Join-Path $devDir "$Name.pid") -Value $p.Id
  return $p
}

$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) { throw "node.exe not found on PATH — install Node.js or add it to PATH." }
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtualenv not found at $python — run the project setup first." }

if ($Restart) {
  Write-Host "Restarting: stopping background servers first..." -ForegroundColor Yellow
  & (Join-Path $PSScriptRoot "dev-stop.ps1")
  Start-Sleep -Seconds 1
}

# ------------------------------------------------------------------- backend
if (Backend-Healthy) {
  Write-Host "backend   already running on :$BACKEND_PORT" -ForegroundColor DarkGray
} else {
  Write-Host "backend   starting..." -NoNewline
  Start-Detached -Name "backend" -FilePath $python -ArgList @("-m", "backend.app") -WorkDir $root | Out-Null
  # Wait for /health (not just the port) so Electron sees a ready backend and
  # doesn't spawn a second one of its own.
  if (Wait-For { Backend-Healthy } 45 "the backend") { Write-Host " ok on :$BACKEND_PORT" -ForegroundColor Green }
}

# ---------------------------------------------------------------------- vite
if (Vite-Up) {
  Write-Host "vite      already running on :$VITE_PORT" -ForegroundColor DarkGray
} else {
  Write-Host "vite      starting..." -NoNewline
  # Relative path (run from the frontend dir) sidesteps the space in the repo
  # path that breaks node's argument parsing.
  Start-Detached -Name "vite" -FilePath $node -ArgList @("node_modules\vite\bin\vite.js") -WorkDir $fe | Out-Null
  if (Wait-For { Vite-Up } 30 "the Vite server") { Write-Host " ok on :$VITE_PORT" -ForegroundColor Green }
}

# ------------------------------------------------------------------- electron
$electron = Join-Path $fe "node_modules\electron\dist\electron.exe"
$running = Get-Process electron -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $electron }
if ($running) {
  Write-Host "electron  already running (pid $($running[0].Id))" -ForegroundColor DarkGray
} else {
  Write-Host "electron  launching..." -ForegroundColor Green
  $env:WT_DEV = "1"   # dev mode: load the UI from the Vite server
  Start-Process -FilePath $electron -ArgumentList "." -WorkingDirectory $fe | Out-Null
}

Write-Host ""
Write-Host "Dev environment is up. It keeps running if you close this window." -ForegroundColor Cyan
Write-Host "  logs:  $devDir\*.log"
Write-Host "  stop:  .\scripts\dev-stop.ps1"
