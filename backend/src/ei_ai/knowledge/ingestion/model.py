"""Value types, outcome codes and the error of document extraction. Nothing here holds a file
name, and no message carries document text (D52)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

SCANNED_PDF = "scanned_pdf"
CORRUPT_FILE = "corrupt_file"
PASSWORD_PROTECTED = "password_protected"
NO_TEXT = "no_text"
UNREADABLE_ENCODING = "unreadable_encoding"
FILE_TOO_COMPLEX = "file_too_complex"
PROCESSING_ERROR = "processing_error"

# Receives a percentage 0-100.
Progress = Callable[[int], None]


@dataclass(frozen=True)
class Block:
    """One unit of text that chunks never cross: a PDF page or a heading section."""

    text: str
    page: int | None
    heading_path: tuple[str, ...]


@dataclass(frozen=True)
class ParsedDocument:
    """The blocks of a file in reading order and its page count when the file states one."""

    blocks: tuple[Block, ...]
    page_count: int | None


@dataclass(frozen=True)
class Chunk:
    """A slice ``text[char_start:char_end]`` of the extracted text with its location."""

    ordinal: int
    text: str
    page: int | None
    heading_path: tuple[str, ...]
    char_start: int
    char_end: int
    token_estimate: int


@dataclass(frozen=True)
class ExtractedDocument:
    """The extracted text, its chunks and the page count shown to users."""

    text: str
    chunks: tuple[Chunk, ...]
    page_count: int


class ExtractionOutcome(Exception):
    """An expected, final result for a file that cannot become ready: ``failed`` with a reason,
    or ``not_supported`` (scanned PDF). The message is the reason code only."""

    def __init__(self, status: Literal["failed", "not_supported"], reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
