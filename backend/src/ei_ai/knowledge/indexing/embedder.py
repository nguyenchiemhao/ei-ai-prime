"""Chunk texts to vectors: the ``ChunkEmbedder`` protocol and its gateway implementation (R9).

Inputs are the chunk texts as stored (NFC-normalised by EA-33). Every vector is checked before it
reaches the database: one per input, ``EMBEDDING_DIMENSIONS`` finite values. Nothing here logs.
"""

import math
from collections.abc import Sequence
from typing import Protocol

from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.gateway import ModelGateway
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.vectors.search import EMBEDDING_DIMENSIONS


class EmbeddingShapeError(Exception):
    """The model answered with the wrong number of vectors, a wrong size or non-finite values."""


class ChunkEmbedder(Protocol):
    ref: ModelRef

    async def embed(self, ctx: ModelCallContext, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in text order."""
        ...


def _check(vectors: list[list[float]], expected: int) -> None:
    """Raises ``EmbeddingShapeError`` unless there are ``expected`` well-formed vectors."""
    if len(vectors) != expected:
        raise EmbeddingShapeError("embedding count does not match the inputs")
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingShapeError(f"embedding must have {EMBEDDING_DIMENSIONS} dimensions")
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingShapeError("embedding values must be finite")


class GatewayEmbedder:
    """Embeds through ``ModelGateway.embed`` with the model ``ref``, ``batch_size`` texts a call."""

    def __init__(self, gateway: ModelGateway, ref: ModelRef, batch_size: int = 16) -> None:
        self.ref = ref
        self._gateway = gateway
        self._batch_size = batch_size

    async def embed(self, ctx: ModelCallContext, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in text order; gateway errors (``ModelError``) pass through."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            result = await self._gateway.embed(ctx, self.ref, batch)
            _check(result.vectors, len(batch))
            vectors.extend(result.vectors)
        return vectors
