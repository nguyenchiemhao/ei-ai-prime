"""The ``normalize`` pipeline: cleanup -> NFC -> canonical tone placement (output is NFC)."""

import unicodedata

from ei_ai.vn_text.cleanup import clean
from ei_ai.vn_text.tone import place_tones


def normalize(text: str) -> str:
    """Return the one canonical NFC form of ``text``; idempotent, keeps no state, never logs."""
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    return place_tones(unicodedata.normalize("NFC", clean(text)))
