"""Background update check. Electron's autoUpdater handles the actual install;
this service provides the backend version handshake and a manual check."""
from __future__ import annotations

import httpx

from backend.config import APP_VERSION
from backend.utils.logger import get_logger

log = get_logger(__name__)

# Point at your published releases feed; kept configurable for forks.
RELEASES_URL = "https://api.github.com/repos/Avromiep/whispertext/releases/latest"


async def check_for_updates() -> dict:
    """Return {current, latest, update_available, url}. Never raises."""
    result = {"current": APP_VERSION, "latest": APP_VERSION,
              "update_available": False, "url": ""}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(RELEASES_URL,
                                 headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            data = r.json()
            latest = str(data.get("tag_name", "")).lstrip("v") or APP_VERSION
            result["latest"] = latest
            result["url"] = data.get("html_url", "")
            result["update_available"] = _newer(latest, APP_VERSION)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        log.info("Update check skipped: %s", exc)
    return result


def _newer(a: str, b: str) -> bool:
    def parts(v: str) -> list[int]:
        out = []
        for p in v.split("."):
            digits = "".join(ch for ch in p if ch.isdigit())
            out.append(int(digits) if digits else 0)
        return out
    return parts(a) > parts(b)
