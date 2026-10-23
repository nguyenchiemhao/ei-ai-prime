"""``GatewayReranker``: scores in input order through the Model Gateway, shape checked (R12)."""

from collections.abc import AsyncIterator, Iterator

import pytest
from model_gateway.fakes import CTX, RERANK, RERANK_SERVED, FakeCatalog, build_gateway

from ei_ai.knowledge.retrieval.reranker import GatewayReranker, RerankShapeError
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import ModelGateway
from support.fake_model_server import FakeModelServer, running_fake_model_server


@pytest.fixture
def server() -> Iterator[FakeModelServer]:
    yield from running_fake_model_server()


@pytest.fixture
async def gateway(server: FakeModelServer) -> AsyncIterator[ModelGateway]:
    server.listed_ids = [RERANK_SERVED]
    made = build_gateway(FakeCatalog([RERANK]), local=server)
    try:
        yield made
    finally:
        await made.aclose()


async def test_gateway_reranker_returns_scores_in_input_order(
    server: FakeModelServer, gateway: ModelGateway
) -> None:
    server.rerank_results = [(2, 0.9), (0, 0.1), (1, 0.5)]
    reranker = GatewayReranker(gateway, RERANK.ref)

    scores = await reranker.rerank(CTX, "câu hỏi", ["a", "b", "c"])

    assert reranker.ref == RERANK.ref
    assert scores == [0.1, 0.5, 0.9]
    sent = [r.body for r in server.requests if r.path == "/v1/rerank"]
    assert len(sent) == 1
    assert sent[0]["query"] == "câu hỏi"
    assert sent[0]["documents"] == ["a", "b", "c"]


@pytest.mark.parametrize(
    "results",
    [
        [(0, 0.1), (2, 0.9)],  # a document is missing
        [(0, 0.1), (0, 0.2), (1, 0.3)],  # duplicate index
        [(0, 0.1), (1, 0.2), (3, 0.3)],  # out of range
        [(0, 0.1), (1, 0.2), (-1, 0.3)],  # negative
        [(0, 0.1), (1, 0.2), (2, 0.3), (2, 0.4)],  # too many
    ],
)
async def test_gateway_reranker_rejects_bad_shape(
    server: FakeModelServer, gateway: ModelGateway, results: list[tuple[int, float]]
) -> None:
    server.rerank_results = results
    reranker = GatewayReranker(gateway, RERANK.ref)

    with pytest.raises(RerankShapeError):
        await reranker.rerank(CTX, "q", ["a", "b", "c"])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
async def test_gateway_reranker_rejects_non_finite_scores(
    gateway: ModelGateway, monkeypatch: pytest.MonkeyPatch, bad: float
) -> None:
    from ei_ai.model_gateway.results import RerankResult

    async def answer(*_: object, **__: object) -> RerankResult:
        return RerankResult([(0, 0.5), (1, bad)], str(RERANK.ref), None)

    monkeypatch.setattr(gateway, "rerank", answer)
    reranker = GatewayReranker(gateway, RERANK.ref)

    with pytest.raises(RerankShapeError):
        await reranker.rerank(CTX, "q", ["a", "b"])


async def test_gateway_reranker_skips_empty_input(
    server: FakeModelServer, gateway: ModelGateway
) -> None:
    reranker = GatewayReranker(gateway, RERANK.ref)

    assert await reranker.rerank(CTX, "q", []) == []
    assert server.requests == []


async def test_gateway_reranker_passes_model_unavailable() -> None:
    made = build_gateway(FakeCatalog([RERANK]))  # no rerank base URL: server not started
    try:
        reranker = GatewayReranker(made, RERANK.ref)
        with pytest.raises(ModelError) as error:
            await reranker.rerank(CTX, "q", ["a"])
    finally:
        await made.aclose()

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
