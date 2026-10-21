"""Static Vietnamese vowel tables, built once at import from the letter inventory.

Every table is derived with ``unicodedata`` from the 12 base vowels and the 5 tone marks;
nothing here is hand-typed per character and nothing ever stores input text (R10).
"""

import unicodedata

TONE_MARKS = "\u0300\u0301\u0303\u0309\u0323"
"""Combining tone marks: grave, acute, tilde, hook above, dot below."""

MODIFIERS = "\u0302\u0306\u031b"
"""Combining vowel modifiers: circumflex, breve, horn."""

_TONE_BY_INDEX = ("", "\u0300", "\u0301", "\u0309", "\u0303", "\u0323")
"""Tone index order: none, grave (huyền), acute (sắc), hook (hỏi), tilde (ngã), dot (nặng)."""

_BASE_SPELLINGS = "a a\u0306 a\u0302 e e\u0302 i o o\u0302 o\u031b u u\u031b y".split()

BASE_VOWELS = "".join(unicodedata.normalize("NFC", spelling) for spelling in _BASE_SPELLINGS)
"""The 12 lower-case base vowels: a ă â e ê i o ô ơ u ư y."""

MODIFIED_VOWELS = frozenset(BASE_VOWELS) - frozenset("aeiouy")
"""Base vowels that carry a modifier: ă â ê ô ơ ư."""

VOWEL_NUCLEI = frozenset(
    (
        "a ă â e ê i o ô ơ u ư y "
        "ai ao au ay âu ây eo êu ia iê iu oa oă oe oi oo ôi ơi "
        "ua uâ uê ui uô uơ uy ưa ưi ươ ưu yê "
        "iêu yêu oai oay oeo uây uôi uya uyê uyu ươi ươu"
    ).split()
)
"""Tone-free vowel clusters of Vietnamese syllables (after the initial; ``gi``/``qu`` excluded).

A word whose cluster is not listed is not Vietnamese and keeps its accents ("où", "ciò")."""


def _build_tables() -> tuple[dict[str, tuple[str, int, bool]], dict[tuple[str, int, bool], str]]:
    split: dict[str, tuple[str, int, bool]] = {}
    join: dict[tuple[str, int, bool], str] = {}
    for base in BASE_VOWELS:
        for tone, mark in enumerate(_TONE_BY_INDEX):
            for upper in (False, True):
                char = unicodedata.normalize("NFC", (base.upper() if upper else base) + mark)
                split[char] = (base, tone, upper)
                join[(base, tone, upper)] = char
    return split, join


_SPLIT, _JOIN = _build_tables()

TONED_CHARS: frozenset[str] = frozenset(ch for ch, (_, tone, _) in _SPLIT.items() if tone)
"""Every precomposed Vietnamese vowel that carries a tone mark, both cases."""


def split_char(ch: str) -> tuple[str, int, bool] | None:
    """Return ``(lower-case base vowel, tone index 0-5, is_upper)``, or ``None`` if not a vowel."""
    return _SPLIT.get(ch)


def join_char(base: str, tone: int, upper: bool) -> str:
    """Build the precomposed vowel for a lower-case base vowel, tone index and case."""
    return _JOIN[(base, tone, upper)]
