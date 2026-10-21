"""``strip_accents``: remove Latin diacritics for the keyword index (R7, R8)."""

import re
import unicodedata

# A combining mark right after a Latin letter (ASCII, Latin-1 to Latin Extended-B, Latin
# Extended Additional). Marks after other scripts (Thai, Arabic, ...) are never touched.
_LATIN_MARKS = re.compile("(?<=[A-Za-z\u00c0-\u024f\u1e00-\u1eff])[\u0300-\u036f]+")
_STROKED_D = str.maketrans({"đ": "d", "Đ": "D"})


def strip_accents(text: str) -> str:
    """Return ``text`` as NFC without Latin diacritics (``đ`` -> ``d``); other scripts unchanged.

    Pure, keeps no state, never logs. No cleanup, no tone step, no case change.
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    stripped = _LATIN_MARKS.sub("", unicodedata.normalize("NFD", text))
    return unicodedata.normalize("NFC", stripped.translate(_STROKED_D))
