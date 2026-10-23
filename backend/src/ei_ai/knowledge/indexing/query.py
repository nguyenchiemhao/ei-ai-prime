"""The vector of a search query, made by the same embedder as the chunks (EA-35, R13)."""

from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
from ei_ai.model_gateway.context import ModelCallContext


async def embed_query(embedder: ChunkEmbedder, ctx: ModelCallContext, text: str) -> list[float]:
    """The vector of ``text``; embedder errors pass through. The text is never logged."""
    (vector,) = await embedder.embed(ctx, [text])
    return vector
