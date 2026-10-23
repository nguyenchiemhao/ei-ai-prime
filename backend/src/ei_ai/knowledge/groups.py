"""Group names of a restricted collection: one normal form, so matching is case-insensitive."""

import unicodedata
from collections.abc import Sequence

from ei_ai.knowledge.errors import InvalidGroup

MAX_GROUPS = 20
MAX_GROUP_LENGTH = 64


def normalise_group(raw: str) -> str:
    """One group in NFC, trimmed and lower-cased; ``InvalidGroup`` when it is not acceptable."""
    group = unicodedata.normalize("NFC", raw).strip().lower()
    if not 1 <= len(group) <= MAX_GROUP_LENGTH:
        raise InvalidGroup
    if "," in group or any(unicodedata.category(char) == "Cc" for char in group):
        raise InvalidGroup
    return group


def normalise_groups(raw: Sequence[str]) -> list[str]:
    """The groups in normal form, without duplicates, in first-seen order. Raises
    ``InvalidGroup`` for a bad group or more than 20 groups."""
    seen: dict[str, None] = {}
    for item in raw:
        seen.setdefault(normalise_group(item), None)
    if len(seen) > MAX_GROUPS:
        raise InvalidGroup
    return list(seen)
