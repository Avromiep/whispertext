# Start the full dev environment: Python backend + Vite + Electron.
# Run from the repo root:  .\scripts\dev.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."

Start-Process -WorkingDirectory $root -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList "-m", "backend.app"
Start-Process -WorkingDirectory "$root\frontend" -FilePath "npm" -ArgumentList "run", "dev"
Start-Sleep 3
Set-Location "$root\frontend"
npm run dev:electron
