<#
  Stop the detached WhisperText dev servers started by dev.ps1 (the Python
  backend and the Vite dev server), plus the dev Electron app.

  Run from anywhere:  .\scripts\dev-stop.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "SilentlyContinue"
$root   = (Resolve-Path "$PSScriptRoot\..").Path
$fe     = Join-Path $root "frontend"
$devDir = Join-Path $root ".dev"

function Stop-ByPidFile([string]$Name) {
  $pidFile = Join-Path $devDir "$Name.pid"
  if (Test-Path $pidFile) {
    $procId = Get-Content $pidFile | Select-Object -First 1
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p) { Stop-Process -Id $procId -Force; Write-Host "stopped $Name (pid $procId)" -ForegroundColor Yellow }
    Remove-Item $pidFile -Force
  }
}

# Stop Electron first: in dev it can auto-restart the backend on exit, so
# killing the app before the backend avoids it respawning one mid-teardown.
$electron = Join-Path $fe "node_modules\electron\dist\electron.exe"
Get-Process electron -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $electron } |
  ForEach-Object { Stop-Process -Id $_.Id -Force; Write-Host "stopped electron (pid $($_.Id))" -ForegroundColor Yellow }

# Backend and Vite were started detached with recorded PIDs.
Stop-ByPidFile "backend"
Stop-ByPidFile "vite"

# Fallback: anything still listening on the known dev ports (e.g. started by
# hand, or before PID files existed). Parsed from netstat rather than
# Get-NetTCPConnection, which is CIM-backed and unreliable on some machines.
function Get-ListeningPids([int]$Port) {
  netstat -ano | Select-String ":$Port\s.*LISTENING" |
    ForEach-Object { ($_ -split '\s+')[-1] } |
    Where-Object { $_ -match '^\d+$' -and $_ -ne '0' } | Sort-Object -Unique
}
foreach ($port in 43117, 5173) {
  foreach ($procId in Get-ListeningPids $port) {
    Stop-Process -Id $procId -Force
    Write-Host "stopped process on :$port (pid $procId)" -ForegroundColor Yellow
  }
}

Write-Host "Dev environment stopped." -ForegroundColor Cyan
