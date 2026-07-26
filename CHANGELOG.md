# Changelog

All notable changes to WhisperText are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/) · versioning: SemVer.

## [1.0.20] — 2026-07-22

### Added
- **Custom vocabulary** (Dictation → Vocabulary). Add your own words, names,
  and jargon. They're fed to the speech engine as a recognition hint so they
  transcribe more reliably, and — the part you asked for — each is typed with
  the exact capitalization you enter. Add "GitHub" and a spoken "github"
  comes out "GitHub"; "OAuth", "kubectl", "iPhone" all keep their casing.
  Works on both the local and Groq engines, and applies after AI cleanup so
  nothing re-cases the term.

## [1.0.19] — 2026-07-22

### Changed
- On the Home dashboard's recent activity, double-click a dictation to copy
  it — it briefly shows "Copied" and reverts after a second. The separate
  copy button there is gone (the full History page keeps its copy button).

## [1.0.18] — 2026-07-22

### Changed
- When no speech is detected, the "No speech detected" message now appears
  briefly in the recording pill on screen, instead of as a desktop
  notification sliding in from the corner.

## [1.0.17] — 2026-07-22

### Added
- Recent activity on the Home dashboard now has the same copy, favorite,
  and delete controls as the History page (they appear on hover).

### Changed
- Hands-free dictation now ends on its own when you stop talking, instead
  of recording until you double-tap again. It uses the same voice-activity
  detection as the silence gate, so it also stops if you double-tap to
  start but never actually speak — no more runaway recordings. The pause
  length is adjustable, and auto-stop can be turned off (Hotkeys → Hands-
  free) to keep the old double-tap-to-stop behaviour.

### Fixed
- Desktop notifications were attributed to "electron.app.Electron". They
  now show "WhisperText" as the source.

## [1.0.16] — 2026-07-21

### Fixed
- Silence still typed a word ("yeah", "Thank you") on microphones with a
  high noise floor. 1.0.15 gated on loudness, which cannot work: on a
  noisy input the noise floor and quiet speech overlap almost exactly —
  measured at 0.0113 against 0.0126 peak frame RMS on a virtual mic, an
  11% gap. Recordings are now screened by Silero voice-activity detection,
  which listens for speech structure rather than level. This is the same
  detector the local Whisper engine always had via `vad_filter`, and its
  absence on the Groq path is why only Groq users ever saw a stray word.
  Verified against the actual audio that produced "Thank you.": silence is
  now discarded before upload, while speech recorded in that same room
  still transcribes at every volume down to a peak of 0.02.

## [1.0.15] — 2026-07-21

### Fixed
- Holding the hotkey in a quiet room typed a stray word — usually "So" or
  "Okay". Whisper was trained on captioned video and invents a filler
  rather than returning nothing when handed silence, and the Groq engine
  (unlike the local one) has no voice-activity filter in front of it.
  Auto-gain made it far worse: it divides by the peak, so a near-silent
  buffer was amplified up to 45x into a loud-looking signal before being
  sent. Recordings with no speech in them are now discarded before they
  reach any engine, auto-gain no longer boosts room tone, and a lone
  filler word from audio too faint to contain speech is dropped. Speech
  is unaffected at any volume — an intentional "Okay." still types.
- The recording pill sometimes didn't appear on the hotkey even though
  dictation still worked. The overlay is driven entirely by WebSocket
  events, and three things could strand it: a socket left half-open by
  sleep/resume stayed "open" but silent with no reconnect; a client that
  reconnected mid-dictation was never told recording had already started;
  and a burst of mic-level events could evict the state change from a
  backed-up client's queue. The backend now heartbeats every 5s, replays
  the current state to new subscribers, and never drops a state change in
  favour of a mic level; the UI force-reconnects a socket that goes quiet.
- The overlay window is recreated if its renderer crashes, instead of
  staying invisible until the app restarts.

## [1.0.14] — 2026-07-14

### Changed
- The whole update flow now happens in-app: checking, a live download
  progress bar (MB and percent), then a "Relaunch & update" button once
  it's ready. Installing runs silently and relaunches automatically —
  no installer wizard, and no hand-off to the GitHub releases page.
- The tray's "Check for Updates" now starts a real check as it opens
  the About page, instead of only navigating there.

## [1.0.13] — 2026-07-08

### Added
- Updates now install in the background. When a new version is found it
  downloads automatically, and the About page shows a one-click
  "Restart & install" button — no more manually re-downloading the
  installer from GitHub (the manual link remains as a fallback).

### Fixed
- AI provider cards said "Ready" for every local provider (Ollama,
  LM Studio…) even when nothing was set up. "Ready" now only appears for
  cloud providers with a saved API key, and the provider actually in use
  shows an "In use" badge.

## [1.0.12] — 2026-07-08

### Changed
- AI cleanup is now off by default for new installs — dictation types the
  raw transcription immediately with no extra network round-trip, which is
  also noticeably faster.
- Onboarding no longer asks for an AI cleanup provider or API key. It's a
  power-user feature you can turn on anytime from AI settings, not a setup
  step for everyone.

### Fixed
- The recording overlay pill was hardcoded to the tan palette regardless of
  theme. It now follows the app's light/dark setting.
- Whisper sometimes ends a trailing-off, unfinished sentence with a literal
  "..." — that's now stripped so it doesn't get typed.

## [1.0.11] — 2026-07-08

### Added
- Onboarding's mic test now uses the real global hotkey — hold the
  shortcut you just configured and speak, release to see the
  transcription — instead of a separate click-to-test button.
- Copy-to-clipboard button on each History entry, next to the
  favorite star.
- Models page's Groq Cloud section now shows whether an API key is
  configured.

### Changed
- History page now shows the 5 most recent dictations by default,
  with a "View all" button to expand the full list.

### Fixed
- Removed the leftover hover wiggle from in-page section headings
  (e.g. "Microphone") — it's now limited to the sidebar nav only.

## [1.0.10] — 2026-07-08

### Changed
- Repo made public — "Check for Updates" now genuinely detects releases
  instead of silently falling back (GitHub's API can't see private-repo
  releases without auth, which a distributed desktop app can't safely embed).
- Sidebar nav wiggle now triggers from anywhere on the button (icon,
  padding, whitespace), not just the letters themselves.
- Title bar and taskbar now show the real app icon instead of Electron's
  generic default (the window never had an explicit `icon` set).

### Fixed
- Removed the hover wiggle from page titles (e.g. "About" at the top of
  each page) — it read as unintentional there. Sidebar nav and in-page
  section headings keep it.

## [1.0.9] — 2026-07-07

### Fixed
- The sidebar logo and About page icon were a hardcoded purple box with a
  generic mic glyph — never actually the app's real icon. Both now render
  the real tan waveform icon.
- About page showed the app version only after clicking Check for
  Updates. It's now shown immediately on load.
- Check for Updates result went from a bare badge to a clear up-to-date
  checkmark or a "New version available" badge with a Download button
  linking straight to the release.

## [1.0.8] — 2026-07-07

### Added
- Onboarding now walks new users through getting a free Groq key right
  after permissions — one button to Groq's sign-up page, paste, connect —
  instead of that setup only existing on the Models page post-onboarding.
  "Fully offline" remains an equal, no-signup option.
- The AI-cleanup provider step is now an explicit opt-in checkbox (off by
  default), matching the app's actual behavior everywhere else instead of
  forcing every new user through a provider/key setup they may not want.

## [1.0.7] — 2026-07-07

### Added
- Renamed the project from WhisperType to WhisperText throughout — source,
  docs, project folder, %APPDATA% data directory, and the Windows keyring
  service name for stored API keys. Existing settings, dictation history,
  downloaded models, and API keys migrate automatically on first run via a
  one-time copy (`backend/config.py::_migrate_legacy_app_dir`,
  `backend/utils/encryption.py::migrate_legacy_keys`) — nothing was lost.
- New app icon: an original tan-and-purple waveform mark drawn from the
  app's own recording-overlay visual language (not derived from any other
  product's logo), simplified for legibility down to 16px so the system
  tray icon reads clearly, not just the full-size app icon. Same source
  image drives both, so they always match.
- Pushed the project to GitHub (`Avromiep/whispertext`, private) with a
  proper `LICENSE` (MIT, matching what the README already claimed) and an
  expanded `.gitignore`. Repo/update-check URLs in `package.json` and
  `updater_service.py` now point at the real repo instead of a placeholder.

## [1.0.6] — 2026-07-07

### Fixed
- **Root-caused the "tan theme not showing" report**: not a code regression —
  repeated `Stop-Process -Force` kills during this session's testing bypassed
  Electron's graceful-shutdown hook, orphaning old backend processes. One of
  them kept holding port 43117 and serving its own stale in-memory settings
  (reporting `theme: dark`) even though the correct `theme: light` was
  already saved to disk. Killed all stray processes and confirmed a single
  clean instance now serves the correct settings.
- **Dark-then-tan flash on launch**: `index.html` hardcoded `class="dark"`,
  so the page always painted dark before the async settings fetch resolved
  and flipped it. Added a synchronous inline script that applies a
  `localStorage`-cached theme before first paint (written by `App.tsx`
  whenever the real theme resolves), eliminating the flash on every launch
  after the first.
- `scripts/build-backend.ps1`'s flatten step is idempotent now (see 1.0.5 —
  applied and verified this round).

### Added
- **Backup Groq API key**: Models page → Groq Cloud → "+ Add a backup key".
  If the primary key fails (rate limit, quota exhausted), the pipeline
  automatically retries with the backup key before falling back to local
  Whisper — never loses a dictation to a single account's limits.
- **Hands-free toggle can be disabled**: Hotkeys page — turn off the
  double-tap-to-record feature entirely if you don't use it, removing any
  chance of accidental activation. Off by default disables the timing
  slider and related tips too, not just the hotkey.

## [1.0.5] — 2026-07-07

### Added
- Per-letter "wiggle" hover animation (`WiggleText` component) applied to
  page titles, section headings, and sidebar nav labels — staggered
  per-character wave on hover, pure CSS (`animation-delay: calc(var(--wt-i)
  * 28ms)`), no JS animation loop.

### Changed
- **Main app window retheme**: the "light" theme is now a warm tan palette
  matching the recording overlay (`#e8dcc4`) instead of neutral off-white,
  and is now the default for new installs. Existing installs need the
  Advanced page theme toggle (or a settings patch) to pick it up, since
  pydantic defaults only apply to freshly-created settings files.
- Fixed `scripts/build-backend.ps1`: the flatten-output step failed on a
  second run because it didn't clear the previous build's files before
  moving new ones in (`Move-Item -Force` doesn't merge into an existing
  directory). Now idempotent.

### Verified
- Real Groq transcription benchmark against the actual configured key (not
  a placeholder): 0.23-0.30s steady-state for the same 10s speech clip used
  throughout this session, vs. local `tiny.en`'s ~0.70s best case — a
  genuine ~2-3x speedup, not a projection.
- Rebuilt installer (`WhisperText Setup 1.0.0.exe`, 153.5 MB) and confirmed
  via archive listing that the bundled backend exe and app.asar sizes
  exactly match the freshly-built artifacts, not stale cached copies.

## [1.0.4] — 2026-07-07

### Added
- **Groq cloud transcription engine** (`backend/services/groq_whisper_service.py`).
  Investigated why commercial dictation apps (e.g. WhisperTyping) feel instant:
  they run Whisper on purpose-built inference hardware in the cloud, not a
  local trick. Verified Groq's free tier (2,000 requests/day, no card) and
  their independently-benchmarked 200-300x real-time speed before building
  this, rather than assuming. New `Dictation → Models` page section lets you
  choose Local vs Groq Cloud, with a key field and a live "Test connection"
  check. Automatic fallback to local Whisper if Groq is ever unreachable —
  a dictation is never lost to a network blip.
- Ruled out (with real benchmarks, not marketing claims) two open-source
  "faster" transcription alternatives before landing on Groq: Parakeet TDT
  0.6B (both fp32 and int8) measured *slower* than the already-active
  `tiny.en` Whisper on this CPU (older server chip, no AVX-512/VNNI), and
  distil-whisper showed the same pattern in an earlier round. Local CPU
  transcription on this hardware is already at its realistic ceiling —
  cloud hardware is the only way to meaningfully beat it.

### Changed
- Gemini AI cleanup stays in the app as an explicit off-by-default toggle
  (Dictation page) rather than being removed, per user preference — it's
  already fixed for speed (thinking disabled, ~0.4-0.8s) if turned on.

## [1.0.3] — 2026-07-07

### Changed — pushed further on speed
- Benchmarked model choices against **real synthesized speech** (a synthetic
  sine-tone test had misled earlier readings — Whisper's VAD and decoder
  behave unpredictably on non-speech audio, in one case looping until the
  token limit). On genuine speech, steady-state (model already warm):
  `tiny.en` 0.70s, `base.en` ~1.0s, `small` 3.28s for a 10s clip — all with
  identical, correct transcripts on clean audio.
- Checked `Systran/faster-distil-whisper-small.en` (the distilled model
  billed as much faster): on this CPU it was **not** faster than `base.en`
  or `tiny.en` — distillation mainly trims decoder depth, and encoder cost
  dominates for short utterances. Not adopted.
- Checked `gemini-2.5-flash-lite` and `gemini-2.0-flash` against `2.5-flash`
  (thinking disabled): all landed in the same ~0.4–0.8s band with no
  consistent winner. Kept `2.5-flash`.
- **Switched the active Whisper model to `tiny.en`** (English-only, catalog
  entries added in `config.py`). Trade-off, disclosed here rather than
  silently applied: `tiny.en` is measurably less accurate than `base`/`small`
  on noisy or quiet microphone audio (the benchmark above used clean
  synthesized speech, a best case). Switch back to `base` or `small` anytime
  from the Models page if transcription quality suffers — one click, no
  restart needed since `WhisperService.load_model()` hot-swaps.
- `.en` models require `Dictation → Language` to be pinned (not `auto`);
  already the case in this install (`language=en`).

## [1.0.2] — 2026-07-06

### Fixed — dictation latency
- **Gemini 2.5 Flash "thinking" was adding ~7 seconds per request.** Measured
  directly: 7.7s with default extended reasoning vs 0.7s with it disabled.
  Grammar/punctuation cleanup never benefits from multi-step reasoning, so
  `GeminiProvider` now always sends `thinkingConfig.thinkingBudget: 0` for
  2.5+ models. This was by far the single biggest latency source.
- The backend process had actually crashed/exited during earlier testing —
  dictations were silently timing out against a dead server, which looked
  like "still slow" but was really "not responding." Root-caused via
  `Get-Process`/`netstat`, confirmed dead, relaunched via Electron so the
  backend lifecycle is properly owned again.
- Faster-Whisper now requests `cpu_threads=os.cpu_count()` instead of
  CTranslate2's default of 4 (measured no significant change on this CPU,
  but is a correct default and helps on higher-core machines).

### Changed
- Benchmarked Whisper model sizes on this hardware for a 5s clip:
  tiny 0.49s, base 0.92s, small 2.91s. Switched the active model to **base**
  for a ~3x speed win with a modest accuracy trade-off (switchable back to
  `small` anytime on the Models page).
- AI mode set to **Cloud / Gemini-only** (per user request to prioritize
  speed over hybrid fallback) — removes the fallback-chain retry overhead
  entirely for the common case; hybrid mode remains available and unaffected
  in the UI for anyone who wants automatic failover instead.
- Overlay waveform: increased vertical amplitude and switched to a fast-attack
  /slow-decay envelope so strands visibly move up and down more, including a
  livelier idle "breathing" motion instead of a near-flat line. Canvas height
  increased 52px → 64px to give the larger motion room without clipping.

## [1.0.1] — 2026-07-06

### Fixed
- **Typing engine rewritten to use `SendInput` with `KEYEVENTF_UNICODE`.**
  The previous keystroke simulation pressed real virtual keys (including
  Shift for capitals), so modifiers still held from the push-to-talk combo
  could turn injected letters into shortcuts (Win+I opening Settings,
  Ctrl+letter firing app commands) and produce alt-code garbage such as
  bullet characters. Unicode injection delivers characters as literal text —
  immune to held modifiers — and is batched, fixing the slow typing.
- Typing now waits (up to 2 s) for all physical modifier keys to be released
  before inserting text, then force-clears any stuck logical modifier state.
- Corrected the Win32 `INPUT` struct layout (union must include `MOUSEINPUT`;
  wrong size made `SendInput` silently inject nothing).
- Verified end-to-end against Windows 11 Notepad: capitals, smart quotes,
  em dashes, currency symbols, and newlines all type exactly.

## [1.0.0] — 2026-07-06

### Added
- Global push-to-talk dictation (hold Win+Shift) and hands-free mode
  (double-tap Right Ctrl), configurable.
- Faster-Whisper transcription (tiny→large-v3) with automatic model download,
  CUDA auto-detection, and CPU int8 fallback.
- AI cleanup with 8 style presets and custom instructions.
- Providers: OpenAI, Anthropic, Google Gemini, OpenRouter, Ollama, LM Studio,
  custom OpenAI-compatible endpoints — with live model discovery.
- Cloud / Local / Hybrid modes, cost-minimizing mode, offline mode, automatic
  provider failover with raw-transcript guarantee.
- Typing engine: simulated keystrokes + clipboard fallback with restore.
- Recording overlay with live multi-strand waveform and staged status.
- Settings app: onboarding wizard, Home dashboard, Dictation, AI, Audio,
  Hotkeys, History (search/favorites/export), Models, Advanced, About.
- Command palette (Ctrl+K), system tray, desktop notifications.
- Secure API-key storage (Windows Credential Manager), SQLite history with
  retention policy, structured rotating logs, log export.
- Auto-update wiring (electron-updater) and NSIS installer configuration.
