"""Test-only ``ChunkEmbedder``: deterministic bag-of-words vectors, no model, no network (EA-35).

Each lower-cased word token adds one to dimension ``sha256(token) % 1024``; the sum is
L2-normalised. Texts that share words are near each other, so search tests make sense. A text
without any word maps to dimension 0. ``gate`` pauses every call until it is set; ``fail`` makes
every call raise it. ``calls`` records the number of texts of each call.

Never imported by ``src``.
"""

import asyncio
import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.vectors.search import EMBEDDING_DIMENSIONS

_WORD = re.compile(r"\w+")


def fake_vector(text: str) -> list[float]:
    """The unit vector of ``text`` (see the module docstring)."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    tokens = _WORD.findall(text.lower()) or [""]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        values[0 if not token else int.from_bytes(digest, "big") % EMBEDDING_DIMENSIONS] += 1.0
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


@dataclass
class FakeEmbedder:
    ref: ModelRef = ModelRef("bge-m3", "2026.10")
    gate: asyncio.Event | None = None
    fail: Exception | None = None
    calls: list[int] = field(default_factory=list)

    async def embed(self, ctx: ModelCallContext, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return [fake_vector(text) for text in texts]
