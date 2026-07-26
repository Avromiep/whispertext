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


# --------------------------------------------------------------- custom vocabulary
def build_vocabulary_prompt(words: list[str]) -> str | None:
    """A prompt that biases Whisper toward the user's terms (proper nouns,
    jargon, acronyms). Both engines accept this: local faster-whisper as
    `initial_prompt`, Groq as the `prompt` form field. None if empty."""
    terms = [w.strip() for w in words if w.strip()]
    return ", ".join(terms) if terms else None


def apply_vocabulary_casing(text: str, words: list[str]) -> str:
    """Rewrite each vocabulary term in `text` to its exact spelling, matching
    case-insensitively on token boundaries. So "github"/"Github" both become
    the user's "GitHub", and "oauth" becomes "OAuth". Runs last, after
    formatting, so nothing downstream re-cases the term.

    Boundaries are non-alphanumeric so symbol-bearing terms like "C++" and
    possessives like "GitHub's" are handled; longer phrases are applied first
    so "New York" wins over a bare "York"."""
    for term in sorted((w.strip() for w in words if w.strip()), key=len, reverse=True):
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
            re.IGNORECASE)
        text = pattern.sub(lambda _m, t=term: t, text)
    return text
