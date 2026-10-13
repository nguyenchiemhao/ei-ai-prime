"""Vector helpers. Vectors travel as text literals cast with `::vector` (no pgvector client)."""

import math
from collections.abc import Sequence

EMBEDDING_DIM = 8


def to_vector_literal(values: Sequence[float]) -> str:
    """Return the pgvector text literal, e.g. `[0.1,0.2,...]`, after validating the input."""
    if len(values) != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM} values, got {len(values)}")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("vector values must be finite numbers")
    return "[" + ",".join(repr(float(v)) for v in values) + "]"
