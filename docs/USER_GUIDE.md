# WhisperText — User Guide

## Dictating

| Action | How |
|---|---|
| Push-to-talk | Hold **Win+Shift**, speak, release |
| Hands-free | Double-tap **Right Ctrl**; double-tap again to finish |
| From the tray | Right-click the tray icon → *Start Dictation* |

While recording, a small overlay appears near the bottom of the screen with a
live waveform and timer. When you stop, it walks through *Transcribing →
Cleaning → Typing* and fades away. Your text is typed at the cursor position
of whatever app you were using.

**Tip:** speak punctuation if you like — "comma", "period", "new paragraph",
"bullet point" are converted automatically (Dictation → Spoken punctuation).

## The main window

You'll rarely need it after setup. Open it by double-clicking the tray icon.

- **Home** — live status, today's dictation count, recent activity.
- **Dictation** — language, cleanup toggles, typing speed and method.
- **AI** — provider, API keys, model picker (queried live), style presets,
  Cloud/Local/Hybrid mode, cost-saving and offline switches.
- **Audio** — microphone picker, live level meter, noise/gain/trim toggles,
  one-click mic test.
- **Hotkeys** — rebind push-to-talk and the hands-free toggle; tune the
  double-tap window.
- **History** — searchable past dictations with favorites, delete, CSV export.
  Turn *Save dictation history* off for full privacy mode.
- **Models** — download/switch/delete Whisper models; shows GPU status and a
  recommendation for your hardware.
- **Advanced** — theme, font scale, launch on boot, auto-update, debug logs.
- **About** — versions, hardware, update check.

Press **Ctrl+K** anywhere in the window for the command palette: switch
providers, toggle cleanup, jump to pages — all from the keyboard.
**Ctrl+1…9** jumps straight to a page.

## Choosing an AI setup

- **Cloud (OpenAI / Claude / Gemini / OpenRouter)** — best quality, needs an
  API key and internet. Keys are stored in Windows Credential Manager.
- **Local (Ollama / LM Studio)** — free, fully offline, private. Install
  Ollama, pull a model (the AI page recommends one for your hardware), done.
- **Hybrid (default)** — uses your preferred provider and falls back through
  the others automatically. If everything fails you still get the raw
  transcription. Enable *Minimize API costs* to prefer local models.

## Troubleshooting

- **"No microphone detected"** — check the device in Audio settings, then
  *Test microphone*.
- **Text doesn't appear in some app** — switch Typing method to *clipboard*
  in Dictation settings; some apps block simulated keystrokes.
- **Slow transcription** — pick a smaller Whisper model (Models page), or
  reduce beam size (Advanced).
- **Something else** — Advanced → *Export logs* and inspect
  `%APPDATA%\WhisperText\logs`.
