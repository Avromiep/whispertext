"""In-memory microphone capture with sounddevice.

Records mono 16-bit PCM into RAM (no temp files), publishes live level events
for the overlay waveform, and applies optional normalization / silence trim.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import sounddevice as sd

from backend.models.settings import load_settings
from backend.services.event_bus import bus
from backend.utils.logger import get_logger

log = get_logger(__name__)

MAX_RECORD_SECONDS = 600  # hard safety cap for hands-free mode

# Opening a cold capture device costs 0.2-1.3s on some machines, which clips the
# start of a dictation. So the stream is kept open (warm) between recordings and
# only released after this much idle, balancing instant starts against not
# holding the microphone open forever.
WARM_IDLE_S = 180.0

# If a recording captured much less audio than the key was held for, the mic
# dropped frames or stopped delivering mid-recording — the dictation is likely
# cut off. Normal loss (stream stop latency + last partial block) is ~0.2s, so
# 1.0s is a safe threshold; ignore very short holds where latency dominates.
DROP_WARN_SECONDS = 1.0
DROP_WARN_MIN_HELD = 2.0

# A persistent (warm) capture stream can silently go dead — the driver keeps
# delivering blocks but they're pure digital zeros — after the device is briefly
# grabbed by another app or the old MME interface glitches. A real mic always has
# a noise floor > 0, so an all-zero capture over a real hold means the warm stream
# is stale: drop it so the next dictation reopens a fresh, live one. This bound
# avoids reacting to a momentary tap of the key.
SILENT_STREAM_MIN_HELD = 0.6
# Below this RMS a capture is treated as dead silence (a live mic's ambient noise
# floor sits well above it, ~0.002+; digital/dead silence sits near 0).
SILENT_RMS_EPS = 0.001

# Loudness alone cannot tell speech from room tone: on a noisy input the noise
# floor (measured at 0.0113 peak frame RMS on a Steam virtual mic) overlaps
# quiet speech (0.0126) almost exactly. Silero VAD decides instead — it listens
# for speech structure, not level. This value is only a cheap short-circuit for
# input that is essentially digital silence, well below any real noise floor.
SILENCE_RMS = 0.0005
# Auto-gain divides by the peak, so a near-silent buffer would be amplified up
# to 45x — turning inaudible hiss into a loud signal for Whisper to hallucinate
# words from. Never boost a buffer quieter than this.
MIN_GAIN_PEAK = 0.02


def speech_seconds(audio: np.ndarray, rate: int) -> float:
    """Seconds of actual speech in `audio`, per Silero VAD. 0.0 means silence.

    This is the same detector the local Whisper path gets for free via
    `vad_filter=True`, which is why only the Groq path ever typed a word from
    an empty room. Running it here covers every engine.
    """
    if audio.size == 0:
        return 0.0
    if rate != 16000:  # Silero is 16 kHz only; fall back to the loudness check
        return 1.0 if peak_frame_rms(audio, rate) >= SILENCE_RMS else 0.0
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        segments = get_speech_timestamps(
            audio,
            VadOptions(min_speech_duration_ms=200, min_silence_duration_ms=500,
                       speech_pad_ms=0),  # unpadded: we want the true duration
            sampling_rate=rate)
    except Exception:  # VAD assets unavailable — never block a dictation
        log.exception("VAD unavailable; falling back to a loudness check")
        return 1.0 if peak_frame_rms(audio, rate) >= SILENCE_RMS else 0.0
    return sum(s["end"] - s["start"] for s in segments) / rate


def peak_frame_rms(audio: np.ndarray, rate: int, frame_ms: int = 20) -> float:
    """Loudest short-frame RMS in `audio`.

    Framewise rather than whole-buffer so that a brief word surrounded by
    silence still registers as speech instead of being averaged away.
    """
    if audio.size == 0:
        return 0.0
    frame = max(1, int(rate * frame_ms / 1000))
    n_frames = audio.size // frame
    if n_frames == 0:
        return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
    frames = audio[: n_frames * frame].astype(np.float32).reshape(n_frames, frame)
    return float(np.max(np.sqrt(np.mean(frames ** 2, axis=1))))


def resample_to(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample float32 mono audio from src_rate to dst_rate.

    FFT method (the same one scipy.signal.resample uses): for downsampling,
    truncating the spectrum is an ideal anti-alias low-pass. numpy-only — no
    extra dependency to bundle — and rate-agnostic, so it works for whatever
    native rate the microphone reports on any machine."""
    if src_rate == dst_rate or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    n_src = audio.shape[0]
    n_dst = int(round(n_src * dst_rate / src_rate))
    if n_dst <= 0:
        return np.zeros(0, dtype=np.float32)
    spec = np.fft.rfft(audio)
    dst_bins = n_dst // 2 + 1
    if dst_bins < spec.shape[0]:
        spec = spec[:dst_bins]                      # downsample: drop high freqs
    elif dst_bins > spec.shape[0]:
        spec = np.concatenate([spec, np.zeros(dst_bins - spec.shape[0], dtype=spec.dtype)])
    return (np.fft.irfft(spec, n=n_dst) * (n_dst / n_src)).astype(np.float32)


class AudioService:
    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False
        self._started_at = 0.0
        self._last_speech_s = 0.0
        self._overflows = 0
        self._capture_rate = 0            # rate the mic actually captured at
        self._last_capture: dict | None = None
        self._chunk_sink = None           # optional callable(bytes) fed each block (live streaming)
        self._stream_device = None        # device the warm stream was opened for
        self._idle_timer: threading.Timer | None = None

    def set_chunk_sink(self, sink) -> None:
        """Register a callable to receive each captured block as raw linear16
        bytes (used to stream to Deepgram live). Pass None to detach."""
        self._chunk_sink = sink

    @staticmethod
    def _native_rate(device) -> int | None:
        """The device's native sample rate, so we capture at a rate it supports
        directly instead of forcing the driver to resample."""
        try:
            info = (sd.query_devices(device, "input") if device is not None
                    else sd.query_devices(kind="input"))
            return int(round(info["default_samplerate"]))
        except Exception:
            return None

    @property
    def last_speech_seconds(self) -> float:
        """Speech detected in the most recent recording — see `speech_seconds`."""
        return self._last_speech_s

    @property
    def last_capture(self) -> dict | None:
        """Stats for the most recent recording — held_s, audio_s, dropped_s,
        dropped_pct, overflows, and a `dropped` flag. Drives the mic-drop
        warning and is logged for diagnosing future cut-offs."""
        return self._last_capture

    # ------------------------------------------------------------------ devices
    @staticmethod
    def list_devices() -> list[dict]:
        devices = []
        try:
            default_in = sd.default.device[0]
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    # The same physical mic is listed once per host API (MME,
                    # DirectSound, WASAPI, WDM-KS) with an identical name, so
                    # surface the API — WASAPI is the modern, lower-latency path
                    # and far less prone to the multi-second stalls the legacy
                    # MME interface can hit on USB mics.
                    try:
                        hostapi = sd.query_hostapis(d["hostapi"])["name"]
                    except Exception:
                        hostapi = ""
                    devices.append({
                        "id": i,
                        "name": d["name"],
                        "hostapi": hostapi,
                        "default": i == default_in,
                        "sample_rate": int(d["default_samplerate"]),
                    })
        except sd.PortAudioError:
            log.exception("Could not enumerate audio devices")
        return devices

    # ---------------------------------------------------------------- recording
    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._recording else 0.0

    def tail_audio(self, seconds: float) -> np.ndarray:
        """The last `seconds` of captured audio as float32 mono in [-1, 1].

        Read-only snapshot for live endpointing while recording continues.
        Returns fewer samples than requested early in a recording.
        """
        chunks = self._chunks[:]  # slice snapshots the list; callback only appends
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        target = load_settings().audio.sample_rate
        capture_rate = getattr(self, "_capture_rate", 0) or target
        need = int(seconds * capture_rate)   # chunks are at the capture rate
        collected: list[np.ndarray] = []
        total = 0
        for c in reversed(chunks):
            collected.append(c)
            total += c.shape[0]
            if total >= need:
                break
        pcm = np.concatenate(list(reversed(collected))).flatten()
        if pcm.size > need:
            pcm = pcm[-need:]
        audio = pcm.astype(np.float32) / 32768.0
        # The VAD that consumes this expects the target rate (16 kHz).
        return resample_to(audio, capture_rate, target) if capture_rate != target else audio

    def _audio_callback(self, indata: np.ndarray, frames: int, t, status) -> None:
        """Persistent stream callback. The stream stays open (warm) between
        dictations, so blocks are ignored unless we're actively capturing."""
        if not self._recording:
            return
        if status:
            # input_overflow = frames were lost because we couldn't keep up;
            # counted so a cut-off can be traced to buffer vs device.
            if getattr(status, "input_overflow", False):
                self._overflows += 1
            log.debug("Audio status: %s", status)
        self._chunks.append(indata.copy())
        sink = self._chunk_sink
        if sink is not None:          # live streaming (Deepgram) — cheap enqueue
            try:
                sink(indata.tobytes())
            except Exception:
                pass
        # RMS level (0..1) for the overlay waveform animation.
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)) / 32768.0)
        bus.publish("audio_level", {"level": min(1.0, rms * 8)})
        if time.monotonic() - self._started_at > MAX_RECORD_SECONDS:
            self._recording = False   # hard cap; leave the stream warm to reuse

    def _ensure_stream_locked(self, s) -> None:
        """Guarantee an open, active capture stream for the configured device.
        Reused across dictations, so only the first (cold) open pays the device
        open latency (0.2-1.3s) — later starts are instant."""
        if (self._stream is not None and self._stream.active
                and self._stream_device == s.input_device):
            return
        self._close_stream_locked()
        target = s.sample_rate
        # Capture at the mic's native rate — asking a 44.1k/48k device for 16k
        # makes the driver resample on the fly, a known source of dropouts. We
        # downsample to `target` in software on stop() instead.
        native = self._native_rate(s.input_device)

        def open_at(rate: int) -> None:
            self._stream = sd.InputStream(
                samplerate=rate, channels=1, dtype="int16",
                device=s.input_device, blocksize=int(rate * 0.03),  # 30 ms
                callback=self._audio_callback)
            self._stream.start()
            self._capture_rate = rate

        try:
            open_at(native or target)
        except (sd.PortAudioError, ValueError) as exc:
            self._stream = None
            if native and native != target:
                # Native rate rejected — fall back to the configured rate (driver
                # resamples) rather than failing the dictation.
                log.warning("Native capture at %d Hz failed (%s); using %d Hz", native, exc, target)
                try:
                    open_at(target)
                except (sd.PortAudioError, ValueError) as exc2:
                    self._stream = None
                    raise RuntimeError(f"No microphone available: {exc2}") from exc2
            else:
                raise RuntimeError(f"No microphone available: {exc}") from exc
        self._stream_device = s.input_device

    def start(self) -> None:
        """Begin capture. Instant when the stream is warm; a cold device open
        costs 0.2-1.3s. Raises RuntimeError if no mic available."""
        with self._lock:
            if self._recording:
                return
            self._cancel_idle_timer_locked()
            s = load_settings().audio
            self._ensure_stream_locked(s)
            self._chunks = []
            self._overflows = 0
            self._started_at = time.monotonic()
            self._recording = True
        log.info("Recording started (device=%s, capture=%d Hz -> %d Hz)",
                 s.input_device, self._capture_rate, s.sample_rate)

    # ------------------------------------------------------- warm-stream mgmt
    def _close_stream_locked(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except (sd.PortAudioError, ValueError):
                pass
            finally:
                self._stream = None
                self._stream_device = None

    def _reinit_audio_locked(self) -> None:
        """Drop the stream and reinitialize PortAudio. After a sleep/resume the
        device can still 'open' but deliver only silence until the audio backend
        is refreshed — a fresh process reads the same mic fine. Reinitializing
        clears that stale state so the next open captures live audio, without the
        user having to restart the app."""
        self._close_stream_locked()
        try:
            sd._terminate()
            sd._initialize()
            log.info("Reinitialized audio backend (PortAudio) after a silent capture")
        except Exception as exc:
            log.warning("Audio backend reinit failed: %s", exc)

    def _cancel_idle_timer_locked(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _schedule_idle_close_locked(self) -> None:
        self._cancel_idle_timer_locked()
        self._idle_timer = threading.Timer(WARM_IDLE_S, self._close_if_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _close_if_idle(self) -> None:
        with self._lock:
            self._idle_timer = None
            if not self._recording:
                self._close_stream_locked()
                log.info("Released idle microphone (warm stream closed)")

    def stop(self) -> np.ndarray:
        """Stop capture and return float32 mono audio normalized to [-1, 1].

        Also records capture stats (`last_capture`): if the mic delivered far
        less audio than the key was held for, it dropped frames or stopped
        mid-recording, so the dictation is cut off — flagged and logged."""
        with self._lock:
            self._recording = False
            held = time.monotonic() - self._started_at
            overflows = self._overflows
            pcm = (np.concatenate(self._chunks).flatten() if self._chunks
                   else np.zeros(0, dtype=np.int16))
            self._chunks = []
            # A dead capture reads as (near-)silence over a real hold even though
            # a fresh *process* opens the same device fine — classic stale audio
            # state after the machine sleeps/resumes or a device glitch. A live
            # mic always has a noise floor (ambient RMS ~0.002+); a dead one sits
            # near 0. Reopening the stream isn't enough here — PortAudio itself is
            # stale — so reinitialize the whole audio backend before the next open.
            rms = (float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) / 32768
                   if pcm.size else 0.0)
            dead_stream = rms < SILENT_RMS_EPS and held >= SILENT_STREAM_MIN_HELD
            if dead_stream:
                self._reinit_audio_locked()
            elif not load_settings().audio.keep_mic_warm:
                self._close_stream_locked()
            else:
                self._schedule_idle_close_locked()   # keep warm for an instant next start

        # Use the rate we actually captured at (may be the mic's native rate).
        capture_rate = self._capture_rate or load_settings().audio.sample_rate
        audio_s = len(pcm) / capture_rate
        dropped = max(0.0, held - audio_s)
        is_drop = dropped >= DROP_WARN_SECONDS and held >= DROP_WARN_MIN_HELD
        self._last_capture = {
            "held_s": round(held, 2), "audio_s": round(audio_s, 2),
            "dropped_s": round(dropped, 2),
            "dropped_pct": round(100 * dropped / held, 1) if held > 0 else 0.0,
            "overflows": overflows, "dropped": is_drop,
        }
        if dead_stream:
            log.warning("Capture came back silent (RMS %.5f) over %.1fs held — stale audio "
                        "state (e.g. after sleep/resume); reinitialized the audio backend so "
                        "the next dictation reopens a live mic. device=%s", rms, held,
                        load_settings().audio.input_device)
        if is_drop:
            log.warning("Audio capture DROPPED %.1fs of %.1fs held (%.0f%%, %d overflow(s)) "
                        "— mic likely glitched or was grabbed by another app. device=%s",
                        dropped, held, self._last_capture["dropped_pct"], overflows,
                        load_settings().audio.input_device)
        else:
            log.info("Recording stopped: %.2fs of audio (held %.2fs, %d overflow(s))",
                     audio_s, held, overflows)
        if pcm.size == 0:
            return np.zeros(0, dtype=np.float32)
        return self._post_process(pcm, capture_rate)

    def _post_process(self, pcm: np.ndarray, capture_rate: int | None = None) -> np.ndarray:
        s = load_settings().audio
        target = s.sample_rate
        if capture_rate is None:
            capture_rate = target
        audio = pcm.astype(np.float32) / 32768.0
        # Downsample the native-rate capture to the rate the engines/VAD expect.
        if capture_rate != target and audio.size:
            audio = resample_to(audio, capture_rate, target)

        # Checked before any gain: if nothing was actually said, hand back an
        # empty buffer so no engine ever sees silence to invent words from.
        if audio.size:
            self._last_speech_s = speech_seconds(audio, s.sample_rate)
            if self._last_speech_s == 0.0:
                log.info("Discarding recording with no speech (%.2fs, peak frame "
                         "RMS %.4f)", audio.size / s.sample_rate,
                         peak_frame_rms(audio, s.sample_rate))
                return np.zeros(0, dtype=np.float32)

        if s.auto_gain and audio.size:
            peak = float(np.max(np.abs(audio)))
            if MIN_GAIN_PEAK < peak < 0.5:  # boost quiet speech, never room tone
                audio = audio * (0.9 / peak)
        audio = np.clip(audio, -1.0, 1.0)

        if s.silence_trimming and audio.size:
            audio = self._trim_silence(audio, s.sample_rate)
        return audio

    @staticmethod
    def _trim_silence(audio: np.ndarray, rate: int, threshold: float = 0.01) -> np.ndarray:
        frame = int(rate * 0.02)
        if audio.size < frame * 4:
            return audio
        n_frames = audio.size // frame
        rms = np.sqrt(np.mean(
            audio[: n_frames * frame].reshape(n_frames, frame) ** 2, axis=1))
        loud = np.where(rms > threshold)[0]
        if loud.size == 0:
            return audio
        pad = 5  # keep 100 ms of context either side
        start = max(0, (loud[0] - pad)) * frame
        end = min(n_frames, loud[-1] + 1 + pad) * frame
        return audio[start:end]


audio_service = AudioService()
