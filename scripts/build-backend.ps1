# Bundle the Python backend into backend-dist/whispertext-backend.exe with PyInstaller.
# Run from the repo root:  .\scripts\build-backend.ps1
# The Electron installer (npm run dist in frontend/) picks it up via extraResources.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

.\.venv\Scripts\python -m pip install pyinstaller --quiet

.\.venv\Scripts\python -m PyInstaller `
  --name whispertext-backend `
  --distpath backend-dist `
  --workpath build\pyinstaller `
  --specpath build `
  --noconfirm --clean --console `
  --collect-all faster_whisper `
  --collect-all ctranslate2 `
  --collect-all tokenizers `
  --collect-all huggingface_hub `
  --collect-submodules keyring `
  --hidden-import backend.app `
  backend\app.py

# PyInstaller emits a folder build (one-dir) at backend-dist\whispertext-backend\
# Flatten expected exe path for electron-builder extraResources mapping. Clear
# any previously-flattened output first so re-running this script is idempotent
# (Move-Item -Force does not merge into an already-existing destination folder).
if (Test-Path "backend-dist\whispertext-backend\whispertext-backend.exe") {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
    "backend-dist\_internal", "backend-dist\whispertext-backend.exe"
  Move-Item -Force "backend-dist\whispertext-backend\*" "backend-dist\"
  Remove-Item -Recurse -Force "backend-dist\whispertext-backend"
}
Write-Host "Backend bundled to backend-dist\whispertext-backend.exe"
