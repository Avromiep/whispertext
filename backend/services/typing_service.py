"""Text injection engine.

Primary: Windows SendInput with KEYEVENTF_UNICODE. Characters are delivered
as literal text (virtual-key 0), which means:
  * held modifier keys (Win/Shift/Ctrl from the hotkey) can NOT combine with
    the injected characters to trigger shortcuts (no accidental Win+I, etc.);
  * any character types correctly — capitals, curly quotes, em dashes,
    non-Latin scripts — with no Shift simulation and no alt-code fallbacks;
  * input is batched per SendInput call, so it's fast and smooth.

Fallback: clipboard + Ctrl-V (with clipboard restore) — also auto-selected
for long texts. Last resort: leave text on the clipboard and notify.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import keyboard
import pyperclip

from backend.models.settings import load_settings
from backend.services.event_bus import bus
from backend.utils.logger import get_logger

log = get_logger(__name__)

# --------------------------------------------------------------- SendInput ABI
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_TAB = 0x09

ULONG_PTR = ctypes.c_size_t  # pointer-sized integer per the WinAPI definition


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


class _MOUSEINPUT(ctypes.Structure):
    # Required in the union even though unused: it is the largest member and
    # determines sizeof(INPUT) (40 bytes on x64). Without it SendInput sees a
    # wrong cbSize and injects nothing.
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT))


class _INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


def _key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


def _events_for_char(ch: str) -> list[_INPUT]:
    """Down+up INPUT events for one character (UTF-16 aware)."""
    if ch in ("\n", "\r"):
        return [_key_event(vk=VK_RETURN),
                _key_event(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)]
    if ch == "\t":
        return [_key_event(vk=VK_TAB),
                _key_event(vk=VK_TAB, flags=KEYEVENTF_KEYUP)]
    events = []
    utf16 = ch.encode("utf-16-le")  # surrogate pairs become two code units
    for i in range(0, len(utf16), 2):
        unit = int.from_bytes(utf16[i:i + 2], "little")
        events.append(_key_event(scan=unit, flags=KEYEVENTF_UNICODE))
        events.append(_key_event(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    return events


def _send_batch(events: list[_INPUT]) -> None:
    arr = (_INPUT * len(events))(*events)
    sent = ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))
    if sent != len(events):
        raise OSError(f"SendInput injected {sent}/{len(events)} events")


# Physical keys we must wait on before typing: modifiers held for the hotkey
# would otherwise interleave with Enter/Tab events (and confuse target apps).
_MODIFIER_KEYS = ("left windows", "right windows", "shift", "right shift",
                  "ctrl", "right ctrl", "alt", "alt gr")


def get_active_window_title() -> str:
    """Foreground window title, recorded in history. Best-effort."""
    try:
        import win32gui
        return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or ""
    except Exception:
        return ""


class TypingService:
    def inject(self, text: str) -> str:
        """Insert `text` at the current caret. Returns the method used."""
        if not text:
            return "none"
        s = load_settings().typing
        self._wait_for_modifier_release()
        time.sleep(max(0, s.pre_type_delay_ms) / 1000)

        method = s.method
        if method == "auto":
            method = "clipboard" if len(text) > s.instant_paste_threshold else "keystrokes"

        if method == "keystrokes":
            try:
                self._type_unicode(text, s.chars_per_second)
                return "keystrokes"
            except OSError as exc:
                log.warning("Unicode injection failed (%s); using clipboard", exc)

        return self._paste(text, restore=s.restore_clipboard)

    # ------------------------------------------------------------------ typing
    @staticmethod
    def _type_unicode(text: str, chars_per_second: int) -> None:
        """Batched KEYEVENTF_UNICODE injection honoring the configured speed."""
        chunk_chars = 16
        delay_per_chunk = chunk_chars / max(50, chars_per_second)
        buf: list[_INPUT] = []
        count = 0
        for ch in text:
            buf.extend(_events_for_char(ch))
            count += 1
            if count >= chunk_chars:
                _send_batch(buf)
                buf, count = [], 0
                time.sleep(delay_per_chunk)
        if buf:
            _send_batch(buf)

    @staticmethod
    def _wait_for_modifier_release(timeout_s: float = 2.0) -> None:
        """Block until the user physically releases all modifier keys.

        Prevents a still-held Win/Shift/Ctrl (from the push-to-talk combo)
        from combining with injected Enter/Tab or the Ctrl-V paste chord.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if not any(keyboard.is_pressed(k) for k in _MODIFIER_KEYS):
                    return
            except (ValueError, OSError):
                return  # can't query — proceed rather than stall the pipeline
            time.sleep(0.02)
        # Timed out: clear logical state so the OS doesn't see stuck modifiers.
        for key in _MODIFIER_KEYS:
            try:
                keyboard.release(key)
            except (ValueError, OSError):
                pass
        log.warning("Modifiers still held after %.1fs — forced release", timeout_s)

    # ------------------------------------------------------------------- paste
    @staticmethod
    def _paste(text: str, restore: bool) -> str:
        previous: str | None = None
        try:
            if restore:
                try:
                    previous = pyperclip.paste()
                except pyperclip.PyperclipException:
                    previous = None
            pyperclip.copy(text)
            time.sleep(0.05)  # let clipboard settle before sending the chord
            keyboard.send("ctrl+v")
            time.sleep(0.15)  # target app must read clipboard before restore
            if restore and previous is not None:
                pyperclip.copy(previous)
            return "clipboard"
        except Exception:
            # Last resort: leave the text on the clipboard for manual paste.
            log.exception("Clipboard paste failed")
            try:
                pyperclip.copy(text)
                bus.notify("Couldn't type into this app — text copied to clipboard.",
                           "warning")
                return "clipboard-manual"
            except pyperclip.PyperclipException:
                bus.error("Text insertion failed entirely.")
                return "failed"


typing_service = TypingService()
