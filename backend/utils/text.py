"""Post-processing helpers for raw transcription text."""
from __future__ import annotations

import re

# Whisper models sometimes end a trailing-off utterance with a literal
# ellipsis ("so...") when the speaker stops mid-sentence rather than a full
# stop — dictation users don't want that artifact typed out.
_TRAILING_ELLIPSIS = re.compile(r"\s*(?:\.{2,}|…)+\s*$")


def strip_trailing_ellipsis(text: str) -> str:
    return _TRAILING_ELLIPSIS.sub("", text)


# Whisper was trained on captioned video, so when handed audio with no speech
# it tends to emit a stock filler or caption boilerplate rather than nothing.
# These are only ever discarded when the audio was too quiet to contain speech
# — saying "okay" out loud still types "Okay".
_SILENCE_HALLUCINATIONS = {
    "okay", "ok", "so", "you", "yeah", "yes", "no", "the", "i", "and", "a",
    "uh", "um", "hmm", "mm", "mhm", "ah", "oh", "bye", "goodbye", "hello",
    "thank you", "thanks", "thank you very much", "thanks for watching",
    "thank you for watching", "please subscribe", "subscribe",
    "music", "applause", "silence", "blank_audio", "foreign", "outro",
}

_PUNCT = re.compile(r"[^\w\s]")


def is_silence_hallucination(text: str) -> bool:
    """True if `text` is nothing but a stock filler Whisper invents on silence."""
    normalized = _PUNCT.sub("", text).strip().lower()
    return bool(normalized) and normalized in _SILENCE_HALLUCINATIONS
