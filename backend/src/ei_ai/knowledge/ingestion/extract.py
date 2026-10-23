"""The extraction pipeline: parse -> normalise -> scan check -> join -> chunk."""

import math

from ei_ai import vn_text
from ei_ai.knowledge.ingestion.chunker import BlockSpan, chunk_document
from ei_ai.knowledge.ingestion.docx_parser import parse_docx
from ei_ai.knowledge.ingestion.formats import DocumentFormat
from ei_ai.knowledge.ingestion.markdown_parser import parse_markdown
from ei_ai.knowledge.ingestion.model import (
    CORRUPT_FILE,
    NO_TEXT,
    SCANNED_PDF,
    Block,
    ExtractedDocument,
    ExtractionOutcome,
    ParsedDocument,
    Progress,
)
from ei_ai.knowledge.ingestion.pdf_parser import parse_pdf
from ei_ai.knowledge.ingestion.text_parser import parse_text

MIN_CHARS_PER_PAGE = 50
CHARS_PER_ESTIMATED_PAGE = 3000
BLOCK_SEPARATOR = "\n\n"
_PDF_PROGRESS_SHARE = 80
_CHUNKED_PROGRESS = 90


def _report(progress: Progress | None, percent: int) -> None:
    """Sends ``percent`` to ``progress`` when there is a sink."""
    if progress is not None:
        progress(percent)


def _parse(fmt: DocumentFormat, data: bytes, progress: Progress | None) -> ParsedDocument:
    """The parser of ``fmt``; PDF pages report 0-80."""
    if fmt == "pdf":
        return parse_pdf(data, lambda p: _report(progress, p * _PDF_PROGRESS_SHARE // 100))
    if fmt == "docx":
        return parse_docx(data)
    if fmt == "md":
        return parse_markdown(data)
    return parse_text(data)


def _normalise_block(block: Block) -> Block:
    """LF line endings, then ``vn_text.normalize`` on the text and every heading."""
    text = block.text.replace("\r\n", "\n").replace("\r", "\n")
    return Block(
        text=vn_text.normalize(text).strip(),
        page=block.page,
        heading_path=tuple(vn_text.normalize(title) for title in block.heading_path),
    )


def _check_text(fmt: DocumentFormat, parsed: ParsedDocument, blocks: list[Block]) -> None:
    """Raises the outcome for a PDF with no pages or too little text per page, and for any other
    format without text."""
    letters = sum(len("".join(block.text.split())) for block in blocks)
    if fmt == "pdf":
        if not parsed.page_count:
            raise ExtractionOutcome("failed", CORRUPT_FILE)
        if letters / parsed.page_count < MIN_CHARS_PER_PAGE:
            raise ExtractionOutcome("not_supported", SCANNED_PDF)
    elif letters == 0:
        raise ExtractionOutcome("failed", NO_TEXT)


def _join(blocks: list[Block]) -> tuple[str, list[BlockSpan]]:
    """The blocks joined with a blank line, and where each one sits in the result."""
    parts: list[str] = []
    spans: list[BlockSpan] = []
    offset = 0
    for block in blocks:
        if parts:
            offset += len(BLOCK_SEPARATOR)
        spans.append(BlockSpan(offset, offset + len(block.text), block.page, block.heading_path))
        parts.append(block.text)
        offset += len(block.text)
    return BLOCK_SEPARATOR.join(parts), spans


def extract_document(
    fmt: DocumentFormat, data: bytes, progress: Progress | None = None
) -> ExtractedDocument:
    """Parse, normalise and chunk a file; raises ``ExtractionOutcome`` for an expected failure.

    ``progress`` gets 0-80 while a PDF is read and 90 after chunking.
    """
    parsed = _parse(fmt, data, progress)
    normalised = [_normalise_block(block) for block in parsed.blocks]
    _check_text(fmt, parsed, normalised)
    text, spans = _join([block for block in normalised if block.text])
    chunks = chunk_document(text, spans)
    _report(progress, _CHUNKED_PROGRESS)
    if parsed.page_count:
        page_count = parsed.page_count
    else:
        page_count = max(1, math.ceil(len(text) / CHARS_PER_ESTIMATED_PAGE))
    return ExtractedDocument(text=text, chunks=chunks, page_count=page_count)
