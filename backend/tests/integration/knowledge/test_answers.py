"""EA-37: ``prepare_answer`` on the fixture corpus, then ``stream_answer`` with a scripted model
(AC1, AC3, AC4, AC6)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.answers.events import AnswerDone, AnswerEvent, PassagesFound
from ei_ai.knowledge.answers.service import ANSWER_K, PreparedAnswer, prepare_answer, stream_answer
from ei_ai.knowledge.retrieval.principal import (
    AuthenticatedPrincipal,
    RetrievalPrincipal,
    simulated_principal,
)
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.tenancy.context import TenantContext
from support.answer_questions import (
    ANSWERABLE,
    UNANSWERABLE,
    AnswerCorpus,
    build_answer_corpus,
)
from support.fake_answer_model import FakeAnswerModel
from support.fake_embedder import FakeEmbedder
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder()
MEMBER = AuthenticatedPrincipal(user_id=uuid.uuid4())


@pytest.fixture
async def conn_a(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> AsyncIterator[AsyncConnection]:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        yield conn


@pytest.fixture
async def corpus(conn_a: AsyncConnection, two_orgs: TwoOrgs) -> AnswerCorpus:
    return await build_answer_corpus(conn_a, two_orgs.a, EMBEDDER)


async def prepare(
    conn: AsyncConnection,
    org: OrgRows,
    corpus: AnswerCorpus,
    question: str,
    principal: RetrievalPrincipal = MEMBER,
) -> PreparedAnswer:
    tenant = TenantContext(org_id=org.org_id, user_id=org.user_id)
    ctx = ModelCallContext(org_id=org.org_id, actor="platform-operator")
    return await prepare_answer(
        conn, tenant, question, principal, corpus.scope, embedder=EMBEDDER, ctx=ctx
    )


async def answer(prepared: PreparedAnswer, model: FakeAnswerModel) -> list[AnswerEvent]:
    ctx = ModelCallContext(org_id=prepared.org_id, actor="platform-operator")
    return [e async for e in stream_answer(prepared, model=model, ctx=ctx)]


async def test_answerable_fixture_questions_are_answered_with_citations(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: AnswerCorpus
) -> None:
    for question in ANSWERABLE:
        prepared = await prepare(conn_a, two_orgs.a, corpus, question)
        events = await answer(prepared, FakeAnswerModel())

        assert 1 <= len(prepared.passages) <= ANSWER_K, question
        assert isinstance(events[0], PassagesFound), question
        done = events[-1]
        assert isinstance(done, AnswerDone), question
        assert done.outcome == "answered", question
        assert done.citations == (1,), question


async def test_unanswerable_fixture_questions_are_not_found(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: AnswerCorpus
) -> None:
    not_found = 0
    for question in UNANSWERABLE:
        prepared = await prepare(conn_a, two_orgs.a, corpus, question)
        guess = FakeAnswerModel(deltas=["Chắc là khoảng 5 ngày."])
        events = await answer(prepared, guess)
        done = events[-1]
        assert isinstance(done, AnswerDone)
        not_found += done.outcome == "not_found"

    assert not_found == 10


async def test_anonymous_principal_reads_no_authenticated_or_restricted_passages(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: AnswerCorpus
) -> None:
    anonymous = simulated_principal("anonymous")
    for question in ANSWERABLE:
        prepared = await prepare(conn_a, two_orgs.a, corpus, question, anonymous)

        assert {corpus.key_of(p.collection_id) for p in prepared.passages} <= {"public"}, question
    leave = await prepare(conn_a, two_orgs.a, corpus, ANSWERABLE[3], anonymous)
    assert leave.passages, "the leave question finds the Public passage"
    assert all(corpus.key_of(p.collection_id) == "public" for p in leave.passages)


async def test_restricted_passages_need_the_group(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: AnswerCorpus
) -> None:
    question = "When are salary bands reviewed by the managers committee?"

    plain = await prepare(conn_a, two_orgs.a, corpus, question)
    manager = await prepare(
        conn_a, two_orgs.a, corpus, question, simulated_principal("authenticated", ["managers"])
    )

    assert "managers" not in {corpus.key_of(p.collection_id) for p in plain.passages}
    assert corpus.key_of(manager.passages[0].collection_id) == "managers"


async def test_prepared_answer_uses_simulated_principal(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: AnswerCorpus
) -> None:
    principal = simulated_principal("authenticated", ["managers"])
    assert isinstance(principal, AuthenticatedPrincipal)
    assert principal.user_id is None

    prepared = await prepare(conn_a, two_orgs.a, corpus, ANSWERABLE[0], principal)

    assert prepared.org_id == two_orgs.a.org_id
    assert prepared.simulated is True
    assert prepared.principal_kind == "authenticated"


async def test_sources_and_scores_of_the_first_passage(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: AnswerCorpus
) -> None:
    prepared = await prepare(conn_a, two_orgs.a, corpus, ANSWERABLE[0])
    events = await answer(prepared, FakeAnswerModel())

    first = events[0]
    assert isinstance(first, PassagesFound)
    assert (first.passages[0].title, first.passages[0].section) == (
        "Leave Policy 2026",
        "§4.1 Personal leave",
    )
    assert first.passages[0].score >= 0.35
    assert [p.number for p in first.passages] == list(range(1, len(first.passages) + 1))


async def test_vietnamese_question_gets_vi_language(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: AnswerCorpus
) -> None:
    vietnamese = await prepare(conn_a, two_orgs.a, corpus, ANSWERABLE[0])
    english = await prepare(conn_a, two_orgs.a, corpus, ANSWERABLE[3])
    model, english_model = FakeAnswerModel(), FakeAnswerModel()

    await answer(vietnamese, model)
    await answer(english, english_model)

    assert vietnamese.language == "vi"
    assert "Answer in Vietnamese." in model.calls[0][0].content
    assert english.language == "en"
    assert "Answer in English." in english_model.calls[0][0].content
