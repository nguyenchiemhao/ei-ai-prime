"""Chunking of the extracted text. Chunks never cross a block (a PDF page or a heading section),
so ``page`` and ``heading_path`` are exact. Sizes are estimated tokens, ``ceil(chars / 4)``."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ei_ai.knowledge.ingestion.model import Chunk

TARGET_TOKENS = 400
MAX_TOKENS = 500
OVERLAP_TOKENS = 50
CHARS_PER_TOKEN = 4

_MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN
_MIN_CHARS = TARGET_TOKENS * CHARS_PER_TOKEN
_OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN
_SENTENCE_END = re.compile(r"[.!?…]\s")


@dataclass(frozen=True)
class BlockSpan:
    """Where a block sits in the extracted text, and its location."""

    start: int
    end: int
    page: int | None
    heading_path: tuple[str, ...]


def estimate_tokens(text: str) -> int:
    """The estimated token count: ``ceil(len(text) / 4)``."""
    return -(-len(text) // CHARS_PER_TOKEN)


def _split_point(text: str, start: int) -> int:
    """The end of a chunk that starts at ``start`` and must be cut before the max size.

    The last paragraph break, else sentence end, else whitespace, within the window that keeps
    the chunk between the target and the max; else the hard max.
    """
    low = start + _MIN_CHARS
    high = start + _MAX_CHARS
    paragraph = text.rfind("\n\n", low, high)
    if paragraph >= 0:
        return paragraph
    sentence = [m.start() + 1 for m in _SENTENCE_END.finditer(text, low, high + 1)]
    if sentence:
        return sentence[-1]
    for index in range(high, low - 1, -1):
        if text[index].isspace():
            return index
    return high


def _next_start(text: str, end: int, limit: int) -> int:
    """Where the next chunk starts: about the overlap before ``end``, at a word start."""
    position = end - _OVERLAP_CHARS
    while position < end and not text[position].isspace():
        position += 1
    while position < limit and text[position].isspace():
        position += 1
    return position


def _chunk_block(text: str, span: BlockSpan) -> list[tuple[int, int]]:
    """The ``(start, end)`` offsets of the chunks of one block; none when it is blank."""
    block_end = span.end
    while block_end > span.start and text[block_end - 1].isspace():
        block_end -= 1
    position = span.start
    while position < block_end and text[position].isspace():
        position += 1
    offsets: list[tuple[int, int]] = []
    while position < block_end:
        if block_end - position <= _MAX_CHARS:
            offsets.append((position, block_end))
            break
        end = _split_point(text, position)
        offsets.append((position, end))
        position = _next_start(text, end, block_end)
    return offsets


def chunk_document(text: str, spans: Sequence[BlockSpan]) -> tuple[Chunk, ...]:
    """Chunks of every block in order, with sequential ordinals; ``text[char_start:char_end]``
    is the chunk text."""
    chunks: list[Chunk] = []
    for span in spans:
        for start, end in _chunk_block(text, span):
            piece = text[start:end]
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    text=piece,
                    page=span.page,
                    heading_path=span.heading_path,
                    char_start=start,
                    char_end=end,
                    token_estimate=estimate_tokens(piece),
                )
            )
    return tuple(chunks)
