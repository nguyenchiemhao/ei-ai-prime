"""Supported upload formats, size limits and file-name rules."""

from typing import Literal

from ei_ai import vn_text
from ei_ai.knowledge.errors import InvalidFileName

DocumentFormat = Literal["pdf", "docx", "md", "txt"]

SUPPORTED_EXTENSIONS: dict[str, DocumentFormat] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "md",
    ".txt": "txt",
}
MAX_FILE_BYTES = 52_428_800
ORG_QUOTA_BYTES = 1_073_741_824
FILE_NAME_MAX = 255


def format_for(file_name: str) -> DocumentFormat | None:
    """The format of ``file_name`` by its last suffix, ignoring case; None when unsupported."""
    dot = file_name.rfind(".")
    if dot < 0:
        return None
    return SUPPORTED_EXTENSIONS.get(file_name[dot:].lower())


def _has_control(text: str) -> bool:
    """True when ``text`` holds a C0, DEL or C1 control character."""
    return any(ord(char) < 0x20 or 0x7F <= ord(char) < 0xA0 for char in text)


def clean_file_name(raw: str) -> str:
    """The display name: base name after the last slash or backslash, trimmed and normalised.

    ``InvalidFileName`` unless the result has 1-255 characters and no control character.
    """
    base = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    # Checked before normalising (which drops some) and after (which maps U+2028/9 to LF).
    if _has_control(base):
        raise InvalidFileName
    name = vn_text.normalize(base).strip()
    if not 1 <= len(name) <= FILE_NAME_MAX or _has_control(name):
        raise InvalidFileName
    return name
