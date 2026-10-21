"""Embedding and rerank through the gateway (EA-24 AC1 shapes and usage, pinning per kind)."""

from collections.abc import Callable

import pytest

from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import ModelGateway
from model_gateway.fakes import (
    CTX,
    EMBED,
    EMBED_SERVED,
    LOCAL,
    RERANK,
    RERANK_SERVED,
    Collector,
    FakeCatalog,
)
from support.fake_model_server import FakeModelServer, Reply

MakeGateway = Callable[..., ModelGateway]


async def test_embed_returns_one_vector_per_input_and_usage(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [EMBED_SERVED]
    gateway = make_gateway(FakeCatalog([EMBED]), local=local_server)

    result = await gateway.embed(CTX, EMBED.ref, ["một", "hai"])

    assert result.vectors == [[0.5, 0.0, -0.25], [0.5, 1.0, -0.25]]
    assert result.model_ref == "bge-m3@2026.10"
    assert result.digest == EMBED.digest
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (7, 0)
    assert local_server.paths() == ["/v1/models", "/v1/embeddings"]
    assert local_server.requests[1].body["model"] == EMBED_SERVED


async def test_rerank_returns_index_and_score_pairs(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [RERANK_SERVED]
    gateway = make_gateway(FakeCatalog([RERANK]), local=local_server)

    result = await gateway.rerank(CTX, RERANK.ref, "câu hỏi", ["a", "b", "c"], top_n=2)

    assert result.results == [(0, 1.0), (1, 0.75)]
    assert result.model_ref == "bge-reranker-v2-m3@2026.10"
    assert result.digest == RERANK.digest
    body = local_server.requests[1].body
    assert local_server.requests[1].path == "/v1/rerank"
    assert body == {
        "model": RERANK_SERVED,
        "query": "câu hỏi",
        "documents": ["a", "b", "c"],
        "top_n": 2,
    }


async def test_a_chat_ref_cannot_be_used_for_embeddings(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    catalog = FakeCatalog([LOCAL, EMBED])
    gateway = make_gateway(catalog, local=local_server)

    with pytest.raises(ModelError) as error:
        await gateway.embed(CTX, LOCAL.ref, ["x"])

    assert error.value.code is ModelErrorCode.MODEL_NOT_FOUND
    assert str(error.value) == (
        "no embedding model qwen3-4b-instruct-2507@2026.10 in this Organization's catalog"
    )
    assert catalog.resolves == [(CTX.org_id, "qwen3-4b-instruct-2507@2026.10", "embedding")]
    assert local_server.requests == []


async def test_embed_newer_build_is_pinned_version_unavailable(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = ["bge-m3@sha256-000000000000"]
    gateway = make_gateway(FakeCatalog([EMBED]), local=local_server)

    with pytest.raises(ModelError) as error:
        await gateway.embed(CTX, EMBED.ref, ["x"])

    assert error.value.code is ModelErrorCode.PINNED_VERSION_UNAVAILABLE
    assert local_server.paths() == ["/v1/models"]


async def test_rerank_5xx_is_retried_once(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [RERANK_SERVED]
    local_server.replies.extend([Reply(status=500), Reply(status=500)])
    collector = Collector()
    gateway = make_gateway(FakeCatalog([RERANK]), local=local_server, observers=[collector])

    with pytest.raises(ModelError) as error:
        await gateway.rerank(CTX, RERANK.ref, "q", ["d"])

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert local_server.count("/v1/rerank") == 2
    assert (collector.records[0].kind, collector.records[0].attempts) == ("rerank", 2)


async def test_unconfigured_embedding_provider_is_model_unavailable_without_network(
    make_gateway: MakeGateway,
) -> None:
    gateway = make_gateway(FakeCatalog([EMBED]))

    with pytest.raises(ModelError) as error:
        await gateway.embed(CTX, EMBED.ref, ["x"])

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
