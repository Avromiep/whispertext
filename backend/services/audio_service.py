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


class AudioService:
    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False
        self._started_at = 0.0

    # ------------------------------------------------------------------ devices
    @staticmethod
    def list_devices() -> list[dict]:
        devices = []
        try:
            default_in = sd.default.device[0]
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    devices.append({
                        "id": i,
                        "name": d["name"],
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

    def start(self) -> None:
        """Begin capture immediately. Raises RuntimeError if no mic available."""
        with self._lock:
            if self._recording:
                return
            s = load_settings().audio
            self._chunks = []

            def callback(indata: np.ndarray, frames: int, t, status) -> None:
                if status:
                    log.debug("Audio status: %s", status)
                self._chunks.append(indata.copy())
                # RMS level (0..1) for the overlay waveform animation.
                rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)) / 32768.0)
                bus.publish("audio_level", {"level": min(1.0, rms * 8)})
                if time.monotonic() - self._started_at > MAX_RECORD_SECONDS:
                    self._recording = False
                    raise sd.CallbackStop

            try:
                self._stream = sd.InputStream(
                    samplerate=s.sample_rate,
                    channels=1,
                    dtype="int16",
                    device=s.input_device,
                    blocksize=int(s.sample_rate * 0.03),  # 30 ms blocks
                    callback=callback,
                )
                self._stream.start()
            except (sd.PortAudioError, ValueError) as exc:
                self._stream = None
                raise RuntimeError(f"No microphone available: {exc}") from exc

            self._started_at = time.monotonic()
            self._recording = True
            log.info("Recording started (device=%s, %d Hz)", s.input_device, s.sample_rate)

    def stop(self) -> np.ndarray:
        """Stop capture and return float32 mono audio normalized to [-1, 1]."""
        with self._lock:
            self._recording = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                finally:
                    self._stream = None
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)

            pcm = np.concatenate(self._chunks).flatten()
            self._chunks = []
        log.info("Recording stopped: %.2fs of audio", len(pcm) / load_settings().audio.sample_rate)
        return self._post_process(pcm)

    def _post_process(self, pcm: np.ndarray) -> np.ndarray:
        s = load_settings().audio
        audio = pcm.astype(np.float32) / 32768.0

        if s.auto_gain and audio.size:
            peak = float(np.max(np.abs(audio)))
            if 0 < peak < 0.5:  # boost quiet input, avoid amplifying clipping
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
