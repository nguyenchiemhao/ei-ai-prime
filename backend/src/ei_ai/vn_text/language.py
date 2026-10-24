"""Question language detection (EA-37, R7).

Deterministic and dictionary-free: any Vietnamese-specific letter (``đ``) or a Latin vowel with a
tone mark or vowel modifier means Vietnamese, everything else is English. Limitations: unaccented
Vietnamese is read as English, and accented non-Vietnamese words ("café") count as Vietnamese.
"""

import unicodedata
from typing import Literal

from ei_ai.vn_text.letters import MODIFIERS, TONE_MARKS

Language = Literal["vi", "en"]

_MARKS = frozenset(TONE_MARKS + MODIFIERS)
_LATIN_VOWELS = frozenset("aeiouyAEIOUY")


def detect_language(text: str) -> Language:
    decomposed = unicodedata.normalize("NFD", text)
    previous = ""
    for ch in decomposed:
        if ch in "đĐ" or (ch in _MARKS and previous in _LATIN_VOWELS):
            return "vi"
        previous = ch
    return "en"
