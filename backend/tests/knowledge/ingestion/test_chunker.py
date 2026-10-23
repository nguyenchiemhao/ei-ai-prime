"""Chunk sizes, overlap, block boundaries and offsets."""

import time

from ei_ai.knowledge.ingestion.chunker import (
    MAX_TOKENS,
    OVERLAP_TOKENS,
    TARGET_TOKENS,
    BlockSpan,
    chunk_document,
    estimate_tokens,
)
from ei_ai.knowledge.ingestion.model import Chunk

_SENTENCE = "The quick brown fox jumps over the lazy dog near the river bank. "


def _long_text(sentences: int) -> str:
    return (_SENTENCE * sentences).strip()


def _single(text: str) -> tuple[Chunk, ...]:
    return chunk_document(text, [BlockSpan(0, len(text), None, ())])


def test_constants_and_estimate() -> None:
    assert (TARGET_TOKENS, MAX_TOKENS, OVERLAP_TOKENS) == (400, 500, 50)
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_chunks_within_400_to_500_tokens_except_block_tail() -> None:
    chunks = _single(_long_text(200))
    assert len(chunks) > 3
    for chunk in chunks[:-1]:
        assert TARGET_TOKENS <= chunk.token_estimate <= MAX_TOKENS
    assert chunks[-1].token_estimate <= MAX_TOKENS


def test_unbroken_text_is_cut_at_the_hard_max() -> None:
    chunks = _single("x" * 5000)
    assert chunks[0].token_estimate == MAX_TOKENS
    assert all(c.token_estimate <= MAX_TOKENS for c in chunks)
    assert chunks[-1].char_end == 5000


def test_paragraph_break_is_preferred() -> None:
    text = "a" * 1700 + ".\n\n" + "b" * 1700
    first = _single(text)[0]
    assert first.text == "a" * 1700 + "."


def test_overlap_about_50_tokens() -> None:
    chunks = _single(_long_text(200))
    for left, right in zip(chunks, chunks[1:], strict=False):
        overlap_chars = left.char_end - right.char_start
        assert 150 <= overlap_chars <= 260
        assert right.char_start > left.char_start


def test_no_chunk_crosses_a_block() -> None:
    first, second = _long_text(80), _long_text(80)
    text = first + "\n\n" + second
    spans = [
        BlockSpan(0, len(first), 1, ()),
        BlockSpan(len(first) + 2, len(text), 2, ()),
    ]
    chunks = chunk_document(text, spans)
    for chunk in chunks:
        owner = spans[chunk.page - 1]  # type: ignore[operator]
        assert owner.start <= chunk.char_start and chunk.char_end <= owner.end
    assert {c.page for c in chunks} == {1, 2}
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_chunk_text_equals_extracted_slice() -> None:
    text = _long_text(150)
    for chunk in _single(text):
        assert chunk.text == text[chunk.char_start : chunk.char_end]
        assert chunk.token_estimate == estimate_tokens(chunk.text)
        assert chunk.text == chunk.text.strip()


def test_short_and_blank_blocks() -> None:
    text = "tiny\n\n   "
    chunks = chunk_document(text, [BlockSpan(0, 4, None, ()), BlockSpan(6, 9, None, ())])
    assert [c.text for c in chunks] == ["tiny"]
    assert chunk_document("", []) == ()


def test_chunks_carry_the_block_location() -> None:
    text = "Heading text body"
    chunk = chunk_document(text, [BlockSpan(0, len(text), 4, ("A", "B"))])[0]
    assert (chunk.page, chunk.heading_path) == (4, ("A", "B"))


def test_many_blocks_chunk_in_linear_time() -> None:
    blocks = 50_000
    text = "\n\n".join(["section body text"] * blocks)
    spans: list[BlockSpan] = []
    offset = 0
    for _ in range(blocks):
        spans.append(BlockSpan(offset, offset + 17, None, ()))
        offset += 19
    started = time.perf_counter()
    chunks = chunk_document(text, spans)
    assert len(chunks) == blocks
    assert time.perf_counter() - started < 5
