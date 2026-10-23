"""EA-36 AC6 (the stage) and D8 at the reranker: the rerank scores decide the top-k, a failing
reranker falls back to the vector order, and the reranker only ever sees permitted text."""

import logging
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.retrieval.principal import AuthenticatedPrincipal
from ei_ai.knowledge.retrieval.reranker import Reranker, RerankShapeError
from ei_ai.knowledge.retrieval.scope import KnowledgeScope
from ei_ai.knowledge.retrieval.service import RetrievalResult, retrieve
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.tenancy.context import TenantContext
from support.fake_embedder import FakeEmbedder
from support.fake_reranker import FakeReranker
from support.permission_questions import FLOOD_QUESTION, build_flood_corpus
from support.retrieval_corpus import add_collection, add_indexed_document
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder()
MEMBER = AuthenticatedPrincipal(user_id=uuid.uuid4())
QUESTION = "alpha beta gamma delta epsilon"
# Each chunk shares one word fewer with the question, so the vector order is this order.
CHUNKS = (
    "alpha beta gamma delta epsilon",
    "alpha beta gamma delta",
    "alpha beta gamma",
    "alpha beta",
    "alpha",
    "zeta",
)


async def run(
    conn: AsyncConnection,
    org: OrgRows,
    question: str,
    scope: KnowledgeScope,
    reranker: Reranker | None,
) -> RetrievalResult:
    tenant = TenantContext(org_id=org.org_id, user_id=org.user_id)
    ctx = ModelCallContext(org_id=org.org_id, actor="platform-operator")
    return await retrieve(
        conn, tenant, question, MEMBER, scope, embedder=EMBEDDER, ctx=ctx, reranker=reranker
    )


@pytest.fixture
async def conn_a(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> AsyncIterator[AsyncConnection]:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        yield conn


@pytest.fixture
async def scope(conn_a: AsyncConnection, two_orgs: TwoOrgs) -> KnowledgeScope:
    a = two_orgs.a
    coll, folder = await add_collection(conn_a, a, name="Greek", access_level="public")
    await add_indexed_document(conn_a, a, coll, folder, CHUNKS, embedder=EMBEDDER)
    return KnowledgeScope(a.workspace_id, (coll,))


def texts(result: RetrievalResult) -> list[str]:
    return [passage.text for passage in result.passages]


async def test_no_reranker_keeps_vector_order(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, scope: KnowledgeScope
) -> None:
    result = await run(conn_a, two_orgs.a, QUESTION, scope, None)
    assert texts(result) == list(CHUNKS[:4])
    assert (result.trace.rerank, result.trace.rerank_model) == ("off", None)
    assert all(passage.rerank_score is None for passage in result.passages)


async def test_reranker_order_decides_top_k(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, scope: KnowledgeScope
) -> None:
    reranker = FakeReranker(score=lambda query, document: float(CHUNKS.index(document)))
    result = await run(conn_a, two_orgs.a, QUESTION, scope, reranker)
    assert texts(result) == list(reversed(CHUNKS))[:4]
    trace = result.trace
    assert (trace.rerank, trace.rerank_model) == ("applied", "bge-reranker-v2-m3@2026.10")
    assert [hit.rerank_score for hit in trace.candidates] == [5.0, 4.0, 3.0, 2.0, 1.0, 0.0]
    assert all(hit.retrieval_score is not None for hit in trace.candidates)
    assert trace.passage_chunk_ids == tuple(hit.chunk_id for hit in trace.candidates[:4])
    for passage, hit in zip(result.passages, trace.candidates, strict=False):
        assert (passage.rerank_score, passage.retrieval_score) == (
            hit.rerank_score,
            hit.retrieval_score,
        )
    assert reranker.seen == [list(CHUNKS)]  # every candidate, in vector order


async def test_rerank_ties_keep_retrieval_order(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, scope: KnowledgeScope
) -> None:
    result = await run(conn_a, two_orgs.a, QUESTION, scope, FakeReranker())
    assert texts(result) == list(CHUNKS[:4])
    assert result.trace.rerank == "applied"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            ModelError(ModelErrorCode.MODEL_UNAVAILABLE, "bge-reranker-v2-m3@2026.10", "rerank"),
            "MODEL_UNAVAILABLE",
        ),
        (RerankShapeError(), "RerankShapeError"),
    ],
    ids=["model-error", "shape-error"],
)
async def test_rerank_failure_falls_back_to_vector_order(
    conn_a: AsyncConnection,
    two_orgs: TwoOrgs,
    scope: KnowledgeScope,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    code: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger="ei_ai.knowledge.retrieval")
    reranker = FakeReranker(score=lambda query, document: float(CHUNKS.index(document)), fail=error)
    result = await run(conn_a, two_orgs.a, QUESTION, scope, reranker)
    assert texts(result) == list(CHUNKS[:4])
    assert (result.trace.rerank, result.trace.rerank_model) == (
        "unavailable",
        "bge-reranker-v2-m3@2026.10",
    )
    assert all(hit.rerank_score is None for hit in result.trace.candidates)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == [
        f"retrieval_rerank_failed org_id={two_orgs.a.org_id} error={code}"
    ]
    assert [r for r in caplog.records if "alpha" in r.getMessage()] == []


async def test_reranker_sees_only_permitted_text(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    flood = await build_flood_corpus(conn_a, two_orgs.a, EMBEDDER)
    reranker = FakeReranker()
    result = await run(conn_a, two_orgs.a, FLOOD_QUESTION, flood.scope, reranker)
    assert {passage.collection_id for passage in result.passages} == {flood.public}
    assert len(reranker.seen) == 1
    assert sorted(reranker.seen[0]) == sorted(flood.public_texts)
    assert FLOOD_QUESTION not in reranker.seen[0]


async def test_reranker_not_called_without_candidates(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    coll, _folder = await add_collection(conn_a, two_orgs.a, name="Empty", access_level="public")
    reranker = FakeReranker()
    result = await run(
        conn_a, two_orgs.a, QUESTION, KnowledgeScope(two_orgs.a.workspace_id, (coll,)), reranker
    )
    assert result.passages == ()
    assert result.trace.candidates == ()
    assert (result.trace.rerank, result.trace.rerank_model) == ("off", "bge-reranker-v2-m3@2026.10")
    assert reranker.seen == []
