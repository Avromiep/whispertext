"""Active-window context for per-tab formatting.

The plain window title is all most apps expose, but for per-tab layout we want
the browser's page title AND URL. Chrome/Edge put the page in the foreground
window's UIA tree directly; Arc wraps Chromium in a WinUI shell whose title is
just "Arc", with the real content in a nested Chrome_WidgetWin child window.

`get_active_context()` returns (title, url) for the foreground window, reading
the browser document via UI Automation when possible. Best-effort and heavily
guarded — it must never raise into, or noticeably slow, the dictation pipeline,
so callers gate it on the per-tab feature being configured.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from backend.utils.logger import get_logger

log = get_logger(__name__)

# Chromium content lives in windows of these classes (the top-level browser
# window for Chrome/Edge, or a nested child inside Arc's WinUI shell).
_CHROMIUM_CLASSES = ("Chrome_WidgetWin_1", "Chrome_RenderWidgetHostHWND")
_MAX_NODES = 400          # bound the UIA walk so a huge a11y tree can't stall us


def _foreground_hwnd() -> int:
    try:
        import win32gui
        return win32gui.GetForegroundWindow()
    except Exception:
        return 0


def _window_title(hwnd: int) -> str:
    try:
        import win32gui
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""


def _chromium_hwnds(hwnd: int) -> list[int]:
    """The window itself plus any Chromium content child windows (Arc case)."""
    import win32gui
    hwnds: list[int] = []
    try:
        if win32gui.GetClassName(hwnd) in _CHROMIUM_CLASSES:
            hwnds.append(hwnd)
    except Exception:
        pass

    def _walk(parent: int) -> None:
        def _cb(child: int, _) -> bool:
            try:
                if win32gui.GetClassName(child) in _CHROMIUM_CLASSES:
                    hwnds.append(child)
            except Exception:
                pass
            return True
        try:
            win32gui.EnumChildWindows(parent, _cb, None)
        except Exception:
            pass

    _walk(hwnd)
    return hwnds


def _doc_from_element(root, budget: list[int]) -> tuple[str, str]:
    """First non-empty (name, value) DocumentControl under `root`. `budget` is a
    single-item list acting as a shared node counter across the walk."""
    stack = [root]
    while stack and budget[0] > 0:
        ctrl = stack.pop()
        budget[0] -= 1
        try:
            if ctrl.ControlTypeName == "DocumentControl":
                name = ctrl.Name or ""
                value = ""
                try:
                    value = ctrl.GetValuePattern().Value or ""
                except Exception:
                    value = ""
                if name or value:
                    return name, value
        except Exception:
            pass
        try:
            stack.extend(ctrl.GetChildren())
        except Exception:
            pass
    return "", ""


def _browser_title_url(hwnd: int) -> tuple[str, str]:
    """(page title, url) from the browser at `hwnd`, or ("", "") if unreadable."""
    hwnds = _chromium_hwnds(hwnd)
    if not hwnds:
        return "", ""                     # not a browser — skip the UIA import
    try:
        import uiautomation as auto
    except Exception:
        return "", ""
    budget = [_MAX_NODES]
    for h in hwnds:
        try:
            ctrl = auto.ControlFromHandle(h)
        except Exception:
            continue
        if ctrl is None:
            continue
        name, value = _doc_from_element(ctrl, budget)
        if value or name:
            return name, value
        if budget[0] <= 0:
            break
    return "", ""


def phrase_matches(phrases, *texts: str) -> bool:
    """True if any configured phrase appears (case-insensitive) in any of the
    given strings — used to match the window title / page title / URL."""
    hay = " ".join(t for t in texts if t).lower()
    return any(p.strip() and p.strip().lower() in hay for p in phrases)


def get_active_context() -> tuple[str, str]:
    """(window title, browser url). URL is '' for non-browsers or when it can't
    be read. Never raises."""
    hwnd = _foreground_hwnd()
    if not hwnd:
        return "", ""
    title = _window_title(hwnd)
    url = ""
    try:
        page_title, page_url = _browser_title_url(hwnd)
        url = page_url
        # Arc's window title is just "Arc" — prefer the real page title when we
        # got one, so title-based matching works there too.
        if page_title and (not title or title.strip().lower() == "arc"):
            title = page_title
    except Exception as exc:
        log.debug("browser context read failed: %s", exc)
    return title, url
