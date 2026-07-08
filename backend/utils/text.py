"""Post-processing helpers for raw transcription text."""
from __future__ import annotations

import re

# Whisper models sometimes end a trailing-off utterance with a literal
# ellipsis ("so...") when the speaker stops mid-sentence rather than a full
# stop — dictation users don't want that artifact typed out.
_TRAILING_ELLIPSIS = re.compile(r"\s*(?:\.{2,}|…)+\s*$")


def strip_trailing_ellipsis(text: str) -> str:
    return _TRAILING_ELLIPSIS.sub("", text)
