# WhisperText — Implementation Plan

Living document. Updated as milestones complete.

## Architecture decisions (deviations from spec, with reasons)

| Decision | Spec said | We chose | Why |
|---|---|---|---|
| Desktop shell | Tauri (preferred) or Electron | **Electron** | No Rust/MSVC toolchain on this machine; spec explicitly allows Electron. Electron also gives first-class transparent overlay + tray support on Windows. |
| Audio capture | sounddevice or PyAudio | **sounddevice** | Modern, NumPy-native, low-latency WASAPI support. |
| Speech engine | Faster-Whisper default | **faster-whisper (CTranslate2)** with auto GPU detect → CPU int8 fallback | Per spec. Dev machine GPU (Quadro M2000, Maxwell) predates CTranslate2 CUDA support, so CPU int8 is the local path; CUDA is auto-used on capable machines. |
| Global hotkeys | — | Python `keyboard` library (low-level WinAPI hook) | Electron globalShortcut cannot detect key *release* (needed for hold-to-talk) or double-tap. The `keyboard` lib supports both with <20 ms latency. |
| Typing engine | Simulate keystrokes, clipboard fallback | `keyboard.write()` (SendInput) primary, clipboard+Ctrl-V fallback with clipboard restore | Per spec. |
| API key storage | OS credential store | `keyring` → Windows Credential Manager | Per spec. |
| Settings | JSON/TOML human readable | JSON at `%APPDATA%/WhisperText/settings.json` | Per spec. |
| History | SQLite | SQLite via stdlib `sqlite3`, WAL mode | Per spec. |

## Milestones

- [x] 1. Project setup — venv, Node.js install, folder structure
- [x] 2. Backend core — config, settings model, logging, database
- [x] 3. Services — audio, whisper, LLM providers, typing, hotkeys, hardware detection
- [x] 4. API layer — FastAPI routes + WebSocket event bus
- [x] 5. Backend tests — pytest suite for core services
- [x] 6. Frontend shell — Electron main (tray, overlay, settings window), Vite+React+TS+Tailwind
- [x] 7. UI pages — onboarding wizard, Home, Dictation, AI, Audio, Hotkeys, History, Models, Advanced, About
- [x] 8. Overlay — waveform animation, status transitions (Listening→Transcribing→Cleaning→Typing)
- [x] 9. System tray — menu, double-click open settings
- [x] 10. Auto updater — electron-updater wiring + backend version check
- [x] 11. Integration testing — pipeline end-to-end, frontend build
- [x] 12. Verified live: onboarding wizard E2E, all 9 pages, overlay record/hide cycle,
      real mic capture + Whisper transcription, Electron launch w/ tray + window
- [~] 13. Packaging — electron-builder (NSIS) + PyInstaller script (`scripts/build-backend.ps1`)
      in place; installer build is a release-time step (not run in this session)
- [x] 14. Documentation — README, USER_GUIDE, DEVELOPER_GUIDE, CHANGELOG

## Verification log (2026-07-06)

- `pytest backend/tests` — 17/17 passed (settings merge, history CRUD, retry
  backoff, provider chain/hybrid/offline/cost logic, silence trim, double-tap
  and hold-release hotkey detection, hardware recommendations).
- `npm run build` — strict tsc + vite build clean.
- Live API smoke test: /health, /system/info (hardware correctly detected:
  Quadro M2000 → CUDA rejected, CPU int8), /providers, /audio/devices (real
  Razer mic found).
- Whisper `small` auto-downloaded and loaded on CPU.
- Onboarding walked end-to-end in browser against live backend, including a
  real 4-second mic recording → transcription (correct "no speech" result).
- Overlay: waveform + timer shown during a real hands-free record cycle via
  /dictation/toggle; auto-hid on idle.
- Electron: launched with tray + WhisperText window, reused running backend.

## Known follow-ups

- Run `scripts/build-backend.ps1` + `npm run dist` on a release machine to
  produce the NSIS installer (PyInstaller bundle of faster-whisper is large).
- Point the `publish`/releases URLs at the real GitHub repository.
- Optional: hold-to-talk live key test (unit-tested; low-level hook verified
  installed — full test requires physically pressing keys).

## Event flow

Hotkey (Python hook) → AudioService.record (RAM) → WhisperService.transcribe →
LLMService.cleanup (provider chain w/ retry + hybrid fallback) → TypingService.inject →
history saved. Every stage broadcasts over WebSocket → Electron overlay + settings UI.

## Provider chain (hybrid mode)

configured provider → fallback provider(s) → raw Whisper text. Transcription is never lost.
