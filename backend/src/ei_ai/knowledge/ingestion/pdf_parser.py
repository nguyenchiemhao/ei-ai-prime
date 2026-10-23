"""PDF parsing: one block per page."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import DependencyError

from ei_ai.knowledge.ingestion.model import (
    CORRUPT_FILE,
    PASSWORD_PROTECTED,
    PROCESSING_ERROR,
    Block,
    ExtractionOutcome,
    ParsedDocument,
    Progress,
)


def _open_reader(data: bytes) -> PdfReader:
    """The reader, decrypted with an empty password when the file is encrypted."""
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        try:
            opened = reader.decrypt("")
        except DependencyError as error:
            raise ExtractionOutcome("failed", PROCESSING_ERROR) from error
        except Exception as error:
            raise ExtractionOutcome("failed", PASSWORD_PROTECTED) from error
        if not opened:
            raise ExtractionOutcome("failed", PASSWORD_PROTECTED)
    return reader


def parse_pdf(data: bytes, progress: Progress | None = None) -> ParsedDocument:
    """One block per page (1-based page numbers); ``progress`` gets 0-100 over the pages.

    Raises ``ExtractionOutcome``: ``password_protected``, or ``corrupt_file`` for anything else
    that stops pypdf.
    """
    try:
        reader = _open_reader(data)
        total = len(reader.pages)
        blocks: list[Block] = []
        for index, page in enumerate(reader.pages):
            blocks.append(Block(page.extract_text() or "", index + 1, ()))
            if progress is not None:
                progress((index + 1) * 100 // total)
    except ExtractionOutcome:
        raise
    except Exception as error:
        raise ExtractionOutcome("failed", CORRUPT_FILE) from error
    return ParsedDocument(tuple(blocks), total)
