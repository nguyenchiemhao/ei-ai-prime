"""Invisible/special-character cleanup (R5) and the combining-mark reorder (R15).

Removes invisible characters that split words (zero-width space, word joiner, BOM, soft hyphen,
C0/C1 controls except tab, LF, VT, FF, CR), maps exotic Unicode spaces one-for-one to U+0020 and
the Unicode line/paragraph separators to LF. Runs of spaces, line endings, ZWJ/ZWNJ, variation
selectors, emoji modifiers and U+FFFD are kept, so code layout and emoji sequences survive.
"""

import re
import unicodedata

from ei_ai.vn_text.letters import MODIFIERS, TONE_MARKS, TONED_CHARS

_REMOVED = "\u200b\u2060\ufeff\u00ad\x7f" + "".join(
    chr(code) for code in [*range(0x00, 0x09), *range(0x0E, 0x20), *range(0x80, 0xA0)]
)
_TO_SPACE = "\u00a0\u1680\u202f\u205f\u3000" + "".join(chr(c) for c in range(0x2000, 0x200B))
_TO_NEWLINE = "\u2028\u2029"

_TABLE = str.maketrans(
    {ch: None for ch in _REMOVED} | {ch: " " for ch in _TO_SPACE} | {ch: "\n" for ch in _TO_NEWLINE}
)

# A tone mark (combining, or inside a precomposed Vietnamese vowel) followed by vowel modifiers.
# Circumflex/breve share combining class 230 with the tone marks, so NFC would leave the pair
# uncomposed; moving the modifiers first lets "e" + acute + circumflex compose to "ế".
_TONE_THEN_MODIFIER = re.compile(
    f"([{''.join(sorted(TONED_CHARS))}]|[{TONE_MARKS}]+)([{MODIFIERS}]+)"
)


def _modifiers_first(match: re.Match[str]) -> str:
    head = unicodedata.normalize("NFD", match[1])
    base = head.rstrip(TONE_MARKS)
    return base + match[2] + head[len(base) :]


def clean(text: str) -> str:
    """Remove invisible characters, map exotic spaces and put vowel modifiers before tones."""
    return _TONE_THEN_MODIFIER.sub(_modifiers_first, text.translate(_TABLE))
