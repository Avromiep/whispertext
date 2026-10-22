"""A short controller buzz when recording actually starts.

A wired Xbox (XInput) controller buzzes the moment the first microphone block
after recording begins arrives — a quiet, hands-free "it's listening now" cue.
The shape is chosen by `audio.vibrate_style` (double tap by default; also strong
or gentle). Entirely optional and defensive: no controller, no XInput, or any
failure => silent no-op and recording behaves exactly as before.

Stdlib only (ctypes/XInput); no new dependency, no network. XInput reaches only
the two main rumble motors (the Series X|S trigger motors aren't addressable).
"""
from __future__ import annotations

import atexit
import ctypes
import queue
import sys
import threading
from ctypes import POINTER, byref, c_ubyte, c_uint32, c_ushort, c_short

from backend.models.settings import DEFAULT_VIBRATE_STYLE as DEFAULT_STYLE, load_settings
from backend.utils.logger import get_logger

log = get_logger(__name__)

FULL = 65535                   # both motors, full power
MAX_ON_SECONDS = 0.6           # cap per segment
MAX_TOTAL_SECONDS = 1.0        # cap for the whole pattern
# Each style is a sequence of (strength for BOTH motors, seconds); strength 0 is
# a pause between pulses. The left motor is the heavy low-frequency one, so both
# run together for the strongest feel.
PATTERNS = {
    "single": ((FULL, 0.25),),                           # "Single tap" — one double-tap tap
    "gentle": ((40000, 0.20),),
    "strong": ((FULL, 0.40),),
    "double": ((FULL, 0.25), (0, 0.15), (FULL, 0.25)),   # "Double tap"
}

ERROR_SUCCESS = 0
_SENTINEL = object()            # queued to tell the worker to exit


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", c_ushort),
        ("bLeftTrigger", c_ubyte),
        ("bRightTrigger", c_ubyte),
        ("sThumbLX", c_short),
        ("sThumbLY", c_short),
        ("sThumbRX", c_short),
        ("sThumbRY", c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", c_uint32),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", c_ushort),
        ("wRightMotorSpeed", c_ushort),
    ]


class XInputBackend:
    """Thin wrapper over the Windows XInput DLL. All calls are no-ops when XInput
    isn't available, so callers never have to check the platform."""

    def __init__(self) -> None:
        self._dll = None
        self._loaded = False
        self._lock = threading.Lock()

    def _load(self):
        """Load the XInput DLL once per instance (thread-safe). Returns the DLL or
        None. Only this result is cached — controller presence is always fresh."""
        with self._lock:
            if self._loaded:
                return self._dll
            self._loaded = True
            if sys.platform != "win32" or not hasattr(ctypes, "WinDLL"):
                log.info("Rumble: XInput not available")
                return None
            for name in ("xinput1_4.dll", "xinput9_1_0.dll"):
                try:
                    dll = ctypes.WinDLL(name)
                except OSError:
                    continue
                dll.XInputGetState.argtypes = [c_uint32, POINTER(XINPUT_STATE)]
                dll.XInputGetState.restype = c_uint32
                dll.XInputSetState.argtypes = [c_uint32, POINTER(XINPUT_VIBRATION)]
                dll.XInputSetState.restype = c_uint32
                self._dll = dll
                log.info("Rumble: using %s", name)
                return dll
            log.info("Rumble: XInput not available")
            return None

    def first_connected(self) -> int | None:
        """The first connected controller slot (0..3), or None. Never cached, so
        plugging a controller in later just works."""
        dll = self._load()
        if dll is None:
            return None
        state = XINPUT_STATE()
        for slot in range(4):
            try:
                if dll.XInputGetState(slot, byref(state)) == ERROR_SUCCESS:
                    return slot
            except Exception:
                return None
        return None

    def set_motors(self, slot: int, left: int, right: int):
        """Set both rumble motors on `slot`. No-op (returns None) without a DLL."""
        dll = self._load()
        if dll is None:
            return None
        return dll.XInputSetState(slot, byref(XINPUT_VIBRATION(left, right)))

    def stop_all(self) -> None:
        """Zero the motors on every slot. Never raises."""
        dll = self._load()
        if dll is None:
            return
        for slot in range(4):
            try:
                dll.XInputSetState(slot, byref(XINPUT_VIBRATION(0, 0)))
            except Exception:
                pass


class RumbleService:
    def __init__(self, backend: XInputBackend | None = None) -> None:
        self._backend = backend if backend is not None else XInputBackend()
        self._queue: "queue.SimpleQueue" = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._atexit_registered = False
        self._stop_evt = threading.Event()   # set() interrupts an in-progress buzz

    def start(self) -> None:
        """Start the single worker thread. Idempotent; called from app.py at
        startup only (never from the audio callback)."""
        if self._thread is not None:
            return
        if not self._atexit_registered:
            atexit.register(self.stop_all)
            self._atexit_registered = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._worker, name="controller-rumble", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Ask the worker to exit and join it. Used by shutdown and tests. Sets the
        stop event first so a buzz in progress is cut short, not awaited."""
        t = self._thread
        if t is None:
            return
        self._stop_evt.set()
        self._queue.put_nowait(_SENTINEL)
        t.join(timeout)
        self._thread = None

    def stop_all(self) -> None:
        """Zero every motor. Never raises."""
        try:
            self._backend.stop_all()
        except Exception:
            pass

    def request(self) -> None:
        """Ask for one buzz. Called from the AUDIO THREAD, so it must be trivial:
        just enqueue. No locks, settings, logging or ctypes here."""
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass

    def _drain_queue(self) -> bool:
        """Remove everything currently queued; return True if a sentinel was seen."""
        saw_sentinel = False
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _SENTINEL:
                saw_sentinel = True
        return saw_sentinel

    def _worker(self) -> None:
        # Clear any motor a hard-killed previous run might have left spinning.
        self.stop_all()
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                return
            exit_now = self._drain_queue()      # coalesce a burst into one buzz
            try:
                a = load_settings().audio
                if not a.vibrate_controller_on_record:
                    log.debug("Rumble: disabled in settings")
                else:
                    self.pulse(a.vibrate_style)
            except Exception:
                log.exception("Rumble: failed (ignored)")
            # Drop requests that arrived DURING the buzz — never stack them.
            if self._drain_queue():
                exit_now = True
            if exit_now or self._stop_evt.is_set():
                return

    def pulse(self, style: str = DEFAULT_STYLE) -> None:
        """Play one buzz pattern on the first connected controller, then always
        zero the motors. Waits between segments are interruptible (stop() cuts a
        buzz short). No exception ever leaves this method."""
        slot = self._backend.first_connected()
        if slot is None:
            log.debug("Rumble: no controller")
            return
        steps = PATTERNS.get(style, PATTERNS[DEFAULT_STYLE])
        total = 0.0
        aborted = False
        try:
            for strength, secs in steps:
                secs = max(0.0, min(secs, MAX_ON_SECONDS, MAX_TOTAL_SECONDS - total))
                if secs <= 0 or self._stop_evt.is_set():
                    break
                rc = self._backend.set_motors(slot, strength, strength)  # 0 = pause (both motors off)
                if rc not in (0, None):
                    log.info("Rumble: controller not reachable (rc=%s), stopping", rc)
                    aborted = True
                    break
                total += secs
                if self._stop_evt.wait(secs):    # interruptible — not time.sleep
                    aborted = True
                    break
            if not aborted:
                log.info("Rumble: fired on slot %d (style=%s)", slot, style)
        except Exception:
            log.exception("Rumble: pulse failed (ignored)")
        finally:
            try:
                self._backend.set_motors(slot, 0, 0)   # always stop the motors
            except Exception:
                log.exception("Rumble: failed to zero motors (ignored)")


rumble_service = RumbleService()
