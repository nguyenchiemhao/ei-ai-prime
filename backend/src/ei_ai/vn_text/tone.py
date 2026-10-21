"""Canonical tone-mark placement on single Vietnamese syllables (R1, R9).

A word is rewritten only when it is one well-formed syllable (initial + a Vietnamese vowel
nucleus + final) with exactly one tone mark; everything else (foreign words, multi-tone words,
other scripts) is left as is. The tone goes on:

1. the last modified vowel (ă â ê ô ơ ư) of the cluster, if any ("người", "quyển");
2. otherwise, when the syllable has a final consonant, the last vowel ("hoàng", "toán");
3. otherwise (open syllable): the only vowel, the first of two ("hòa", "thủy") or the middle
   of three ("ngoài", "khuỷu").

Every letter keeps its case by position ("HoÀ" -> "HòA").
"""

import re
import string
import unicodedata
from itertools import groupby

from ei_ai.vn_text.letters import (
    MODIFIED_VOWELS,
    TONED_CHARS,
    VOWEL_NUCLEI,
    join_char,
    split_char,
)

_INITIALS = sorted(
    "ngh ng gh gi qu ch kh nh ph th tr b c d đ g h k l m n p q r s t v x".split(),
    key=len,
    reverse=True,
)
_FINALS = frozenset(["", "c", "ch", "m", "n", "ng", "nh", "p", "t"])
_CONSONANTS = frozenset(string.ascii_letters + "đĐ")

# A whole letter run (no letter right before it) that contains a tone-marked vowel. Toneless
# words and other scripts never reach Python code (R10: speed without a cache of input text).
_TONED_WORD = re.compile(f"(?<![^\\W\\d_])[^\\W\\d_]*[{''.join(sorted(TONED_CHARS))}][^\\W\\d_]*")

_Letter = tuple[str, int, bool, bool]
"""(lower-case base letter, tone index, is_upper, is_vowel)."""


def _letters(word: str) -> list[_Letter] | None:
    letters: list[_Letter] = []
    for ch in word:
        vowel = split_char(ch)
        if vowel is not None:
            letters.append((vowel[0], vowel[1], vowel[2], True))
        elif ch in _CONSONANTS:
            letters.append((ch.lower(), 0, ch.isupper(), False))
        else:
            return None
    return letters


def _initial_length(base: str, vowels: list[bool]) -> int | None:
    for initial in _INITIALS:
        if base.startswith(initial):
            size = len(initial)
            if initial == "gi" and not (size < len(base) and vowels[size]):
                return 1
            return size
    return 0 if vowels[0] else None


def _tone_position(letters: list[_Letter]) -> int | None:
    """Index of the letter that must carry the tone, or ``None`` if not one syllable."""
    base = "".join(letter[0] for letter in letters)
    vowels = [letter[3] for letter in letters]
    start = _initial_length(base, vowels)
    if start is None:
        return None
    end = start
    while end < len(letters) and vowels[end]:
        end += 1
    count = end - start
    if base[start:end] not in VOWEL_NUCLEI or base[end:] not in _FINALS:
        return None
    modified = [i for i in range(start, end) if base[i] in MODIFIED_VOWELS]
    if modified:
        return modified[-1]
    if end < len(letters):
        return end - 1
    return start + (1 if count == 3 else 0)


def _rewrite(match: re.Match[str]) -> str:
    word = match[0]
    text = match.string
    start, end = match.span()
    if (end < len(text) and unicodedata.combining(text[end])) or (
        start and unicodedata.combining(text[start - 1])
    ):
        return word
    if word.isalpha():
        return _rewrite_letters(word)
    # A glued non-decimal numeral (superscript, fraction, Roman numeral) is not a letter: rewrite
    # only the alphabetic sub-runs ("Hoà¹" -> "Hòa¹").
    return "".join(
        _rewrite_letters("".join(run)) if is_alpha else "".join(run)
        for is_alpha, run in groupby(word, str.isalpha)
    )


def _rewrite_letters(word: str) -> str:
    letters = _letters(word)
    if letters is None:
        return word
    tones = [letter[1] for letter in letters if letter[1]]
    if len(tones) != 1:
        return word
    target = _tone_position(letters)
    if target is None:
        return word
    return "".join(
        join_char(base, tones[0] if i == target else 0, upper) if is_vowel else word[i]
        for i, (base, _, upper, is_vowel) in enumerate(letters)
    )


def place_tones(text: str) -> str:
    """Move each syllable's tone mark to its canonical vowel. ``text`` must already be NFC."""
    return _TONED_WORD.sub(_rewrite, text)
