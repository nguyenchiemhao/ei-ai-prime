"""The text rules shared by collections and folders."""

import unicodedata

from ei_ai.knowledge.errors import InvalidKnowledgeInput

TEXT_MAX = 200
_CONTROL = "Cc"


def _has_control_character(text: str) -> bool:
    """True when ``text`` holds a control character (NUL, bell, tab, newline, DEL, ...)."""
    return any(unicodedata.category(char) == _CONTROL for char in text)


def clean_name(name: str) -> str:
    """The trimmed name; ``InvalidKnowledgeInput`` unless it has 1-200 characters, none of them
    a control character."""
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= TEXT_MAX or _has_control_character(cleaned):
        raise InvalidKnowledgeInput
    return cleaned


def clean_subtitle(subtitle: str | None) -> str | None:
    """The trimmed subtitle (empty becomes None); ``InvalidKnowledgeInput`` above 200 characters
    or with a control character."""
    if subtitle is None:
        return None
    cleaned = subtitle.strip()
    if len(cleaned) > TEXT_MAX or _has_control_character(cleaned):
        raise InvalidKnowledgeInput
    return cleaned or None
