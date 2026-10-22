"""One short controller buzz when recording actually starts.

A wired Xbox (XInput) controller gives a single ~200 ms rumble the moment the
first microphone block after recording begins arrives — a quiet, hands-free
"it's listening now" cue. Entirely optional and defensive: no controller, no
XInput, or any failure => silent no-op and recording behaves exactly as before.

Stdlib only (ctypes/XInput); no new dependency, no network. XInput reaches only
the two main rumble motors (the Series X|S trigger motors aren't addressable).
"""
from __future__ import annotations

import atexit
import ctypes
import queue
import sys
import threading
import time
from ctypes import POINTER, byref, c_ubyte, c_uint32, c_ushort, c_short

from backend.models.settings import load_settings
from backend.utils.logger import get_logger

log = get_logger(__name__)

RUMBLE_SECONDS = 0.2            # how long the buzz lasts (keep 0.15-0.2)
MAX_RUMBLE_SECONDS = 0.5        # hard cap: the worker never sleeps longer than this
MOTOR_STRENGTH = 45000          # 0..65535, both motors

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

    def start(self) -> None:
        """Start the single worker thread. Idempotent; called from app.py at
        startup only (never from the audio callback)."""
        if self._thread is not None:
            return
        if not self._atexit_registered:
            atexit.register(self.stop_all)
            self._atexit_registered = True
        self._thread = threading.Thread(target=self._worker, name="controller-rumble", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Ask the worker to exit and join it. Used by shutdown and tests."""
        t = self._thread
        if t is None:
            return
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

    def _worker(self) -> None:
        # Clear any motor a hard-killed previous run might have left spinning.
        self.stop_all()
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                return
            # Coalesce a burst of requests into one buzz; a sentinel still wins.
            exit_now = False
            while True:
                try:
                    extra = self._queue.get_nowait()
                except queue.Empty:
                    break
                if extra is _SENTINEL:
                    exit_now = True
            try:
                if not load_settings().audio.vibrate_controller_on_record:
                    log.debug("Rumble: disabled in settings")
                else:
                    self.pulse()
            except Exception:
                log.exception("Rumble: failed (ignored)")
            if exit_now:
                return

    def pulse(self) -> None:
        """Buzz the first connected controller for RUMBLE_SECONDS, then always zero
        the motors. No exception ever leaves this method."""
        slot = self._backend.first_connected()
        if slot is None:
            log.debug("Rumble: no controller")
            return
        try:
            rc = self._backend.set_motors(slot, MOTOR_STRENGTH, MOTOR_STRENGTH)
            log.info("Rumble: fired on slot %d (rc=%s)", slot, rc)
            time.sleep(max(0, min(RUMBLE_SECONDS, MAX_RUMBLE_SECONDS)))
        except Exception:
            log.exception("Rumble: pulse failed (ignored)")
        finally:
            try:
                self._backend.set_motors(slot, 0, 0)   # always stop the motors
            except Exception:
                log.exception("Rumble: failed to zero motors (ignored)")


rumble_service = RumbleService()
