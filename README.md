# WhisperText

**Your AI voice assistant for every application.**

Hold a shortcut. Speak. Release. Polished text appears wherever your cursor is —
in Chrome, Word, Slack, VS Code, or any other app. No copy/paste, no popup
editors, no switching windows.

## How it works

```
Global hotkey → record (in RAM) → Faster-Whisper → AI cleanup → simulated typing
```

- **Push-to-talk**: hold `Win+Shift`, speak, release.
- **Hands-free**: double-tap `Right Ctrl` to start, double-tap again to stop.
- Every stage streams status to a floating overlay (waveform → transcribing →
  cleaning → typing).
- The AI stage fixes grammar, punctuation, and filler words — it never invents
  or removes content. If every AI provider is unreachable, the raw
  transcription is inserted instead: **you never lose a dictation**.

## Features

- **Speech engine**: Faster-Whisper (CTranslate2), tiny→large-v3, automatic
  model download, CUDA auto-detect with CPU int8 fallback.
- **AI providers**: OpenAI, Anthropic, Google Gemini, OpenRouter, Ollama,
  LM Studio, any OpenAI-compatible endpoint. Cloud / Local / **Hybrid** mode
  with automatic failover, cost-minimizing mode, and full offline mode.
- **8 style presets**: Professional, Friendly, Executive, Technical, Medical,
  Legal, Academic, Creative — plus custom instructions.
- **Typing engine**: simulated keystrokes with clipboard-paste fallback
  (and clipboard restore).
- **Privacy**: audio stays in RAM, API keys live in Windows Credential
  Manager, history is local SQLite and can be disabled entirely.
- **Polish**: system tray, command palette (`Ctrl+K`), onboarding wizard,
  dark/light/system themes, hardware-aware local-model recommendations.

## Quick start (from source)

Prereqs: Python 3.11+, Node 20+.

```powershell
git clone <repo> && cd WhisperText
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
.\scripts\dev.ps1        # backend + vite + electron
```

Or run pieces individually:

```powershell
.\.venv\Scripts\python -m backend.app     # backend on http://127.0.0.1:43117
cd frontend && npm run dev                # vite dev server
cd frontend && npm run dev:electron       # electron shell (dev mode)
```

## Building installers

```powershell
.\scripts\build-backend.ps1     # PyInstaller bundle -> backend-dist/
cd frontend && npm run dist     # NSIS installer -> frontend/release/
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest backend/tests -q
cd frontend && npm run typecheck
```

## Project layout

```
backend/            Python service: FastAPI + pipeline
  services/         audio, whisper, llm (+providers/), typing, hotkeys, events
  models/           pydantic settings
  storage/          SQLite history
  utils/            logging, keyring, retry, hardware detection
  api/              REST + WebSocket routes
  tests/            pytest suite
frontend/           Electron + React + TypeScript + Tailwind
  electron/         main process (tray, overlay, updater) + preload
  src/pages/        Onboarding, Home, Dictation, AI, Audio, Hotkeys,
                    History, Models, Advanced, About
  src/overlay/      recording overlay with live waveform
docs/               user & developer guides
```

Settings live at `%APPDATA%\WhisperText\settings.json`; logs and model cache
are alongside it. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for
architecture decisions and milestone status.

## License

MIT
