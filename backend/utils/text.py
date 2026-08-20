"""Post-processing helpers for raw transcription text."""
from __future__ import annotations

import itertools
import re

# Whisper models sometimes end a trailing-off utterance with a literal
# ellipsis ("so...") when the speaker stops mid-sentence rather than a full
# stop — dictation users don't want that artifact typed out.
_TRAILING_ELLIPSIS = re.compile(r"\s*(?:\.{2,}|…)+\s*$")


def strip_trailing_ellipsis(text: str) -> str:
    return _TRAILING_ELLIPSIS.sub("", text)


# Split after sentence-ending punctuation followed by whitespace. A decimal like
# "3.14" has no space after the dot, so it isn't split.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


# "one" is the only number word that's also a pronoun/article, so Deepgram's
# numerals turns "one of them" into "1 of them". These put the WORD back while
# leaving genuine counts ("1 dog", "3 of them", "chapter 1", "type 1") as digits.
def _sentence_initial(text: str, at: int) -> bool:
    j = at - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j < 0 or text[j] in ".!?\n"


def _cap(word: str, text: str, at: int) -> str:
    return word[0].upper() + word[1:] if _sentence_initial(text, at) else word


def _one_cased(text: str, at: int) -> str:
    return _cap("one", text, at)


# A "1" that's really "one" because of what FOLLOWS it (pronoun/idiom).
_ONE_BEFORE = re.compile(
    r"\b1(?=\s+(?:of|another|and\s+only|and\s+the\s+same|or\s+the\s+other|"
    r"at\s+a\s+time|after\s+another|after\s+the\s+other)\b)", re.IGNORECASE)
# A "1" that's really "one" because of the determiner/adjective BEFORE it.
_ONE_AFTER = re.compile(
    r"\b(no|the|this|that|which|each|every|any|another|other|little|big|loved|dear|"
    r"young|old|good|new|main|real|whole|right|wrong|first|last|next|only)\s+1\b",
    re.IGNORECASE)
# "one by one" / "one on one" — both digits become the word.
_ONE_PAIR = re.compile(r"\b1(\s+(?:by|on)\s+)1\b", re.IGNORECASE)


def fix_numeral_idioms(text: str) -> str:
    """Undo digit-ification of "one" where it's a pronoun/article, not a count.
    No-op on text that has no such "1" (e.g. word-based engine output)."""
    text = _ONE_BEFORE.sub(lambda m: _one_cased(m.string, m.start()), text)
    text = _ONE_PAIR.sub(lambda m: _one_cased(m.string, m.start()) + m.group(1) + "one", text)
    text = _ONE_AFTER.sub(lambda m: m.group(1) + " one", text)
    return text


# Ordinals read better as words in prose ("first of all", "give me a second"),
# but Deepgram writes them as "1st"/"2nd". Spell them out — except in dates,
# where the digit form is wanted ("January 1st", "1st of March").
_ORD_ONES = ["", "first", "second", "third", "fourth", "fifth",
             "sixth", "seventh", "eighth", "ninth"]
_ORD_TEENS = ["tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
              "sixteenth", "seventeenth", "eighteenth", "nineteenth"]
_ORD_TENS = ["", "", "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth",
             "seventieth", "eightieth", "ninetieth"]
_TENS_PREFIX = ["", "", "twenty", "thirty", "forty", "fifty", "sixty",
                "seventy", "eighty", "ninety"]
_MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
           r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_ORDINAL = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)


def _ordinal_word(n: int) -> str | None:
    if not 1 <= n <= 99:
        return None
    if n < 10:
        return _ORD_ONES[n]
    if n < 20:
        return _ORD_TEENS[n - 10]
    tens, ones = divmod(n, 10)
    return _ORD_TENS[tens] if ones == 0 else f"{_TENS_PREFIX[tens]} {_ORD_ONES[ones]}"


def fix_ordinal_idioms(text: str) -> str:
    """Spell "1st"/"2nd"/... as words in prose, but keep the digit form in a date
    context (next to a month, or "of {month}"). No-op if there are no digit
    ordinals."""
    def repl(m: re.Match) -> str:
        word = _ordinal_word(int(m.group(1)))
        if word is None:
            return m.group(0)
        before = text[max(0, m.start() - 12):m.start()].lower()
        after = text[m.end():m.end() + 16].lower()
        if re.search(_MONTHS + r"\s*$", before) or re.match(r"\s+of\s+" + _MONTHS + r"\b", after):
            return m.group(0)   # date — keep the digit ordinal
        return _cap(word, text, m.start())
    return _ORDINAL.sub(repl, text)


def sentences_on_separate_lines(text: str) -> str:
    """Put each sentence on its own line, with a blank line between them."""
    parts = [p.strip() for p in _SENTENCE_BOUNDARY.split(text.strip()) if p.strip()]
    return "\n\n".join(parts)


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


_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
          "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
# How a single digit can be spoken. 0 is usually "oh" inside an identifier
# ("rapp02" is said "rapp oh two"), but also "zero"/"o".
_DIGIT_WORDS = {0: ["oh", "zero", "o"], 1: ["one"], 2: ["two"], 3: ["three"], 4: ["four"],
                5: ["five"], 6: ["six"], 7: ["seven"], 8: ["eight"], 9: ["nine"]}

# A vocab term made of letters then digits (rapp11, Rapp02) — the case that
# needs number-aware matching, since the digits get transcribed several ways.
_ALNUM_TERM = re.compile(r"^([A-Za-z]+)(\d+)$")


def _whole_number_words(n: int) -> list[str] | None:
    """Word list for a whole number 0-99: 11 -> ['eleven'], 21 -> ['twenty','one']."""
    if not 0 <= n <= 99:
        return None
    if n < 10:
        return [_ONES[n]]
    if n < 20:
        return [_TEENS[n - 10]]
    tens, ones = divmod(n, 10)
    return [_TENS[tens]] + ([_ONES[ones]] if ones else [])


def _number_form_patterns(digits: str) -> list[str]:
    """Regex fragments matching how the numeric suffix of a term might be
    transcribed: the digits ("11"), spaced digits ("1 1"), a whole-number word
    ("eleven"), or digit-by-digit words ("one one", "oh two")."""
    forms: set[str] = set()
    forms.add(re.escape(digits))                               # "11", "02"
    forms.add(r"\s+".join(re.escape(d) for d in digits))       # "1 1", "0 2"
    n = int(digits)
    if digits == str(n):   # no leading zero -> spoken as a whole number ("eleven")
        words = _whole_number_words(n)
        if words:
            forms.add(r"\s+".join(re.escape(w) for w in words))
    # Digit-by-digit words, incl. "oh"/"zero"/"o" for 0 ("oh two", "one one").
    per_digit = [[re.escape(w) for w in _DIGIT_WORDS[int(d)]] for d in digits]
    for combo in itertools.product(*per_digit):
        forms.add(r"\s+".join(combo))
    return sorted(forms, key=len, reverse=True)                # longest alternative first


def apply_vocabulary_casing(text: str, words: list[str]) -> str:
    """Rewrite each vocabulary term in `text` to its exact spelling. Plain terms
    match case-insensitively on token boundaries, so "github"/"Github" both
    become the user's "GitHub" and "oauth" becomes "OAuth".

    A term that is letters followed by digits (e.g. "rapp11", "Rapp02") also
    matches the ways speech-to-text renders that number — split off with a space
    ("rapp 11"), spelled out ("rapp eleven"), or said digit-by-digit ("rapp oh
    two") — and glues it back to the exact term. Runs last, after formatting, so
    nothing downstream re-cases or re-splits it.

    Boundaries are non-alphanumeric so symbol-bearing terms like "C++" and
    possessives like "GitHub's" are handled; longer terms are applied first so
    "New York" wins over a bare "York"."""
    for term in sorted((w.strip() for w in words if w.strip()), key=len, reverse=True):
        m = _ALNUM_TERM.match(term)
        if m:
            letters, digits = m.group(1), m.group(2)
            number = "|".join(_number_form_patterns(digits))
            pattern = re.compile(
                r"(?<![A-Za-z0-9])" + re.escape(letters) + r"[\s-]*(?:" + number + r")(?![A-Za-z0-9])",
                re.IGNORECASE)
        else:
            pattern = re.compile(
                r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
                re.IGNORECASE)
        text = pattern.sub(lambda _m, t=term: t, text)
    return text
