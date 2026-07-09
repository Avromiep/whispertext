# WhisperText — Developer Guide

## Architecture

Two processes joined by localhost HTTP + WebSocket:

```
Electron (frontend/)                    Python backend (backend/)
├─ main.cjs    tray, windows, updater   ├─ app.py          FastAPI + lifespan wiring
├─ overlay     transparent BrowserWindow├─ api/routes.py   REST + /ws event stream
└─ React SPA   settings UI              ├─ services/
        │                               │   hotkey_service  low-level keyboard hook
        └── http://127.0.0.1:43117 ─────┤   audio_service   sounddevice → RAM buffer
            ws://127.0.0.1:43117/ws     │   whisper_service faster-whisper wrapper
                                        │   llm_service     provider chain + presets
                                        │   providers/      one adapter per API
                                        │   typing_service  SendInput / clipboard
                                        │   pipeline.py     orchestrates the flow
                                        ├─ models/settings  pydantic, JSON on disk
                                        ├─ storage/database SQLite history (WAL)
                                        └─ utils/           logger, keyring, retry, hw
```

**Why hotkeys live in Python:** Electron's `globalShortcut` can't observe key
*release* (needed for hold-to-talk) or double-taps. The `keyboard` package
installs a low-level Windows hook; callbacks are dispatched to worker threads
so the hook never stalls.

**Event flow:** every pipeline stage calls `bus.status(...)` (thread-safe).
The FastAPI WebSocket fans events out to the overlay and settings window.
`audio_level` events (~30/s while recording) drive the overlay waveform.

**Provider abstraction:** `services/providers/base.py` defines
`generate / list_models / validate / shutdown`. OpenAI, OpenRouter, LM Studio,
and custom endpoints share one OpenAI-compatible adapter parameterized by base
URL. Adding a provider = one file + one registry entry in `llm_service.py`.

**Failover:** `LLMService._provider_chain()` builds the ordered provider list
from mode (cloud/local/hybrid), cost-saving, and offline flags. Each provider
gets `retries` attempts with 1s/2s/5s backoff; the final fallback is the raw
transcript.

## Conventions

- Python: full type hints, module-level loggers, no bare `except` outside the
  pipeline boundary and typing engine (which must never crash the app).
- Frontend: strict TypeScript, Tailwind design tokens (`--bg`, `--accent`, …)
  for theming, all state through the settings context (`useSettings`).
- Settings writes are atomic (temp file + replace); API keys go through
  `utils/encryption.py` only.

## Dev loops

```powershell
.\.venv\Scripts\python -m backend.app                # backend, hot code = restart
cd frontend && npm run dev                           # vite HMR at :5173
cd frontend && npm run dev:electron                  # electron pointing at :5173
.\.venv\Scripts\python -m pytest backend/tests -q    # unit tests
cd frontend && npm run typecheck                     # strict tsc
```

The backend can be developed without Electron: the React app runs in a plain
browser at `http://localhost:5173` (Electron-only APIs are behind the
`bridge?` null check).

## Packaging

1. `scripts/build-backend.ps1` → PyInstaller one-dir bundle in `backend-dist/`.
2. `cd frontend && npm run dist` → NSIS installer in `frontend/release/`;
   electron-builder copies `backend-dist/` into the installer via
   `extraResources` and `main.cjs` spawns it in packaged mode.
3. Auto-updates use electron-updater's GitHub provider (`publish` block in
   `package.json`); the backend also exposes `/updates/check` for the UI.
4. **Every GitHub release must attach three files** from `frontend/release/`:
   the installer exe, its `.exe.blockmap`, and `latest.yml`. electron-updater
   reads `latest.yml` from the newest release to discover updates and the
   blockmap to download only the changed blocks — without them, installed
   apps can't self-update and fall back to the manual GitHub download link.

## Extending

- **New AI provider**: subclass `AIProvider`, register in `PROVIDER_CLASSES`,
  add a `ProviderConfig` default in `models/settings.py`.
- **New speech engine**: implement the `WhisperService` interface
  (`transcribe(np.ndarray) -> TranscriptionResult`) and swap in `pipeline.py`.
- **New settings**: add to the pydantic model (defaults keep old configs
  valid), surface in the relevant page via `patch({...})`.
