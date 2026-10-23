"""Reading an upload body: the size cap and a single buffer per upload."""

import tracemalloc

import pytest
from starlette.requests import Request

from ei_ai.api.documents import _read_body
from ei_ai.knowledge.errors import FileTooLarge
from ei_ai.knowledge.ingestion.formats import MAX_FILE_BYTES

_CHUNK = 64 * 1024


def _request(total: int) -> Request:
    """A request whose body streams ``total`` bytes in 64 KiB chunks."""
    left = total

    async def receive() -> dict[str, object]:
        nonlocal left
        piece = min(left, _CHUNK)
        left -= piece
        return {"type": "http.request", "body": b"x" * piece, "more_body": left > 0}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


async def test_body_is_kept_in_one_buffer_without_a_final_copy() -> None:
    size = 16 * 1024 * 1024
    request = _request(size)
    tracemalloc.start()
    try:
        body = await _read_body(request)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(body) == size
    assert peak < size * 1.5


async def test_body_over_the_limit_is_abandoned() -> None:
    with pytest.raises(FileTooLarge):
        await _read_body(_request(MAX_FILE_BYTES + 1))
