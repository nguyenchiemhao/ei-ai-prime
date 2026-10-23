"""``GatewayEmbedder``: batches of 16 through the Model Gateway, every vector checked (R9)."""

from collections.abc import AsyncIterator, Iterator

import pytest
from model_gateway.fakes import CTX, EMBED, EMBED_SERVED, FakeCatalog, build_gateway

from ei_ai.knowledge.indexing.embedder import EmbeddingShapeError, GatewayEmbedder
from ei_ai.model_gateway.gateway import ModelGateway
from support.fake_model_server import FakeModelServer, running_fake_model_server


@pytest.fixture
def server() -> Iterator[FakeModelServer]:
    yield from running_fake_model_server()


@pytest.fixture
async def gateway(server: FakeModelServer) -> AsyncIterator[ModelGateway]:
    server.listed_ids = [EMBED_SERVED]
    made = build_gateway(FakeCatalog([EMBED]), local=server)
    try:
        yield made
    finally:
        await made.aclose()


async def test_gateway_embedder_batches_and_checks_dimensions(
    server: FakeModelServer, gateway: ModelGateway
) -> None:
    server.dimensions = 1024
    embedder = GatewayEmbedder(gateway, EMBED.ref)
    texts = [f"đoạn {n}" for n in range(33)]

    vectors = await embedder.embed(CTX, texts)

    assert embedder.ref == EMBED.ref
    assert server.count("/v1/embeddings") == 3
    sent = [r.body["input"] for r in server.requests if r.path == "/v1/embeddings"]
    assert [len(batch) for batch in sent] == [16, 16, 1]
    assert [text for batch in sent for text in batch] == texts
    assert len(vectors) == 33
    assert all(len(vector) == 1024 for vector in vectors)
    # The fake server puts the position inside the request at index 1: input order is kept.
    assert [vector[1] for vector in vectors] == [float(n % 16) for n in range(33)]


async def test_gateway_embedder_refuses_vectors_of_the_wrong_size(
    server: FakeModelServer, gateway: ModelGateway
) -> None:
    server.dimensions = 3
    embedder = GatewayEmbedder(gateway, EMBED.ref)

    with pytest.raises(EmbeddingShapeError):
        await embedder.embed(CTX, ["một", "hai"])


async def test_gateway_embedder_without_texts_calls_nothing(
    server: FakeModelServer, gateway: ModelGateway
) -> None:
    embedder = GatewayEmbedder(gateway, EMBED.ref)

    assert await embedder.embed(CTX, []) == []
    assert server.requests == []
