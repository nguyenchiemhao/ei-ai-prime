"""TXT parsing and the shared text decoder."""

import charset_normalizer

from ei_ai.knowledge.ingestion.model import (
    UNREADABLE_ENCODING,
    Block,
    ExtractionOutcome,
    ParsedDocument,
)

_UTF8_BOM = b"\xef\xbb\xbf"


def decode_text(data: bytes) -> str:
    """UTF-8 (BOM stripped) first, else the best charset-normalizer guess.

    Raises ``ExtractionOutcome`` (``unreadable_encoding``) when no guess is usable.
    """
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM) :]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    best = charset_normalizer.from_bytes(data).best()
    if best is None:
        raise ExtractionOutcome("failed", UNREADABLE_ENCODING)
    return str(best)


def parse_text(data: bytes) -> ParsedDocument:
    """One block with an empty heading path."""
    return ParsedDocument((Block(decode_text(data), None, ()),), None)
