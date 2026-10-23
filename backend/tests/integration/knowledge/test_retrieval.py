"""EA-36 AC1-AC5, AC7: ``retrieve`` returns only what the principal may read inside the scope,
the permission filter runs inside the vector query, and neither logs nor trace hold any text."""

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.retrieval import service
from ei_ai.knowledge.retrieval.passage_rows import load_passages
from ei_ai.knowledge.retrieval.principal import (
    AuthenticatedPrincipal,
    RetrievalPrincipal,
    session_principal,
    simulated_principal,
)
from ei_ai.knowledge.retrieval.scope import KnowledgeScope, Skipped
from ei_ai.knowledge.retrieval.service import RetrievalResult, retrieve
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.tenancy.context import TenantContext
from support.fake_embedder import FakeEmbedder, fake_vector
from support.permission_questions import (
    ALLOWED,
    FLOOD_QUESTION,
    PERMISSION_QUESTIONS,
    TOPIC_TEXTS,
    PermissionCorpus,
    PrincipalKey,
    build_flood_corpus,
    build_permission_corpus,
)
from support.retrieval_corpus import add_collection, add_folder, add_indexed_document
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder()
MEMBER = AuthenticatedPrincipal(user_id=uuid.uuid4())
MANAGER = simulated_principal("authenticated", ["Managers"])
PRINCIPALS: dict[PrincipalKey, RetrievalPrincipal] = {
    "anonymous": simulated_principal("anonymous"),
    "authenticated": MEMBER,
    "managers": MANAGER,
}
MH_QUESTION = "When are the salary review bands set?"
SENTINEL = "SENTINEL-EA36-7f3a"


async def run(
    conn: AsyncConnection,
    org: OrgRows,
    question: str,
    principal: RetrievalPrincipal,
    scope: KnowledgeScope,
    k: int = 4,
) -> RetrievalResult:
    tenant = TenantContext(org_id=org.org_id, user_id=org.user_id)
    ctx = ModelCallContext(org_id=org.org_id, actor="platform-operator")
    return await retrieve(conn, tenant, question, principal, scope, embedder=EMBEDDER, ctx=ctx, k=k)


def collections_of(result: RetrievalResult) -> list[uuid.UUID]:
    return [passage.collection_id for passage in result.passages]


@pytest.fixture
async def conn_a(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> AsyncIterator[AsyncConnection]:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        yield conn


@pytest.fixture
async def corpus(conn_a: AsyncConnection, two_orgs: TwoOrgs) -> PermissionCorpus:
    return await build_permission_corpus(conn_a, two_orgs.a, EMBEDDER)


@pytest.mark.parametrize("key", list(PRINCIPALS))
async def test_principal_collection_matrix(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus, key: PrincipalKey
) -> None:
    returned: set[str] = set()
    for item in PERMISSION_QUESTIONS:
        result = await run(conn_a, two_orgs.a, item.question, PRINCIPALS[key], corpus.scope, 10)
        returned |= {corpus.key_of(collection) for collection in collections_of(result)}
    assert returned == ALLOWED[key]
    assert not returned & {"out_of_scope", "other_workspace"}
    trace = result.trace
    assert {corpus.key_of(collection) for collection in trace.searched} == ALLOWED[key]
    expected_skipped = {
        Skipped("collection", corpus.collections[name], "no_access")
        for name in ("authenticated", "managers", "hr")
        if name not in ALLOWED[key]
    } | {Skipped("collection", corpus.collections["other_workspace"], "not_found")}
    assert set(trace.skipped) == expected_skipped


async def _check_questions(
    conn: AsyncConnection, org: OrgRows, corpus: PermissionCorpus, key: PrincipalKey
) -> None:
    for item in PERMISSION_QUESTIONS:
        result = await run(conn, org, item.question, PRINCIPALS[key], corpus.scope, 10)
        keys = [corpus.key_of(collection) for collection in collections_of(result)]
        assert set(keys) <= item.allowed[key], item.question
        if item.topic_collection in item.allowed[key]:
            assert keys[0] == item.topic_collection, item.question


async def test_permission_questions_anonymous_gets_only_public(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus
) -> None:
    await _check_questions(conn_a, two_orgs.a, corpus, "anonymous")


async def test_permission_questions_authenticated_never_restricted(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus
) -> None:
    await _check_questions(conn_a, two_orgs.a, corpus, "authenticated")


async def test_permission_questions_managers(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus
) -> None:
    await _check_questions(conn_a, two_orgs.a, corpus, "managers")


async def test_manager_gets_manager_handbook_non_manager_gets_none(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus
) -> None:
    mh = corpus.collections["managers"]
    managers = await run(conn_a, two_orgs.a, MH_QUESTION, MANAGER, corpus.scope)
    assert collections_of(managers).count(mh) >= 1
    member = await run(conn_a, two_orgs.a, MH_QUESTION, MEMBER, corpus.scope)
    assert mh not in collections_of(member)
    assert Skipped("collection", mh, "no_access") in member.trace.skipped


async def test_restricted_flood_does_not_empty_valid_results(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    flood = await build_flood_corpus(conn_a, two_orgs.a, EMBEDDER)
    # Force the HNSW index (on a tiny table the planner would scan and sort instead).
    await conn_a.execute(text("SET LOCAL enable_seqscan = off"))
    await conn_a.execute(text("SET LOCAL enable_sort = off"))
    result = await run(conn_a, two_orgs.a, FLOOD_QUESTION, MEMBER, flood.scope)
    assert len(result.passages) == 4
    assert set(collections_of(result)) == {flood.public}
    assert {hit.collection_id for hit in result.trace.candidates} == {flood.public}
    assert len(result.trace.candidates) == 6
    # Control: the flood chunks match better, so a manager gets them first.
    managers = await run(conn_a, two_orgs.a, FLOOD_QUESTION, MANAGER, flood.scope)
    assert set(collections_of(managers)) == {flood.restricted}


async def test_out_of_scope_collection_never_returned(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus
) -> None:
    question = "How fast are expense claims paid?"
    out = corpus.collections["out_of_scope"]
    result = await run(conn_a, two_orgs.a, question, MEMBER, corpus.scope, 10)
    assert out not in collections_of(result)
    assert corpus.collections["other_workspace"] not in collections_of(result)
    assert out not in result.trace.searched
    # Control: in scope, it is the best match.
    wider = KnowledgeScope(two_orgs.a.workspace_id, (*corpus.scope.collection_ids, out))
    assert collections_of(await run(conn_a, two_orgs.a, question, MEMBER, wider))[0] == out


async def test_folder_scope_returns_only_that_folder_tree(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    coll, f1 = await add_collection(conn_a, a, name="Expenses", access_level="authenticated")
    f1a = await add_folder(conn_a, a, coll, parent_id=f1, name="f1a")
    f2 = await add_folder(conn_a, a, coll, name="f2")
    question = "How fast are expense claims paid?"
    for folder, chunk in ((f1, "expense claims"), (f1a, "claims paid"), (f2, question)):
        await add_indexed_document(conn_a, a, coll, folder, [chunk], embedder=EMBEDDER)
    scope = KnowledgeScope(a.workspace_id, folder_ids=(f1,))
    result = await run(conn_a, a, question, MEMBER, scope, 10)
    assert {passage.folder_id for passage in result.passages} == {f1, f1a}
    assert result.trace.searched == (coll,)
    # The sibling folder's chunk is the best match and in a readable collection, yet never comes.
    whole = await run(conn_a, a, question, MEMBER, KnowledgeScope(a.workspace_id, (coll,)))
    assert whole.passages[0].folder_id == f2


async def test_empty_scope_returns_nothing_without_vector_query(
    conn_a: AsyncConnection,
    two_orgs: TwoOrgs,
    corpus: PermissionCorpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_query(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("nearest must not run for an empty readable scope")

    monkeypatch.setattr(service, "nearest", no_query)
    a = two_orgs.a
    restricted = (corpus.collections["managers"], corpus.collections["hr"])
    for principal, scope in (
        (MANAGER, KnowledgeScope(a.workspace_id)),
        (PRINCIPALS["anonymous"], KnowledgeScope(a.workspace_id, restricted)),
    ):
        result = await run(conn_a, a, MH_QUESTION, principal, scope)
        assert result.passages == ()
        assert result.trace.candidates == ()
        assert result.trace.searched == ()
    assert {item.reason for item in result.trace.skipped} == {"no_access"}


async def test_trace_records_searched_skipped_ids_and_scores(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus
) -> None:
    # Shares words with all four permitted chunks, so every candidate scores above 0.
    question = "How many of the 14 annual leave days does an employee get from 8:00?"
    result = await run(conn_a, two_orgs.a, question, MEMBER, corpus.scope, 2)
    trace = result.trace
    ids = corpus.collections
    assert (trace.principal, trace.simulated, trace.group_count) == ("authenticated", False, 0)
    assert (trace.retrieval, trace.rerank, trace.rerank_model) == ("vector", "off", None)
    assert trace.embedding_model == "bge-m3@2026.10"
    assert trace.searched == (ids["public"], ids["authenticated"])
    assert trace.skipped == (
        Skipped("collection", ids["managers"], "no_access"),
        Skipped("collection", ids["hr"], "no_access"),
        Skipped("collection", ids["other_workspace"], "not_found"),
    )
    assert len(trace.candidates) == 4
    assert {hit.collection_id for hit in trace.candidates} == {ids["public"], ids["authenticated"]}
    scores = [hit.retrieval_score for hit in trace.candidates]
    assert all(0 < score <= 1 for score in scores)
    assert scores == sorted(scores, reverse=True)
    assert all(hit.rerank_score is None for hit in trace.candidates)
    assert len(result.passages) == 2
    assert trace.passage_chunk_ids == tuple(p.chunk_id for p in result.passages)
    assert trace.passage_chunk_ids == tuple(hit.chunk_id for hit in trace.candidates[:2])
    for passage, hit in zip(result.passages, trace.candidates, strict=False):
        assert (passage.document_id, passage.collection_id) == (hit.document_id, hit.collection_id)
        assert passage.retrieval_score == hit.retrieval_score
        assert passage.rerank_score is None
        # retrieval_score = 1 - cosine distance = the dot product of the two unit vectors
        pairs = zip(fake_vector(question), fake_vector(passage.text), strict=True)
        dot = sum(x * y for x, y in pairs)
        assert passage.retrieval_score == pytest.approx(dot, abs=1e-5)
    assert result.passages[0].text == TOPIC_TEXTS["authenticated"][0]
    assert set(trace.timings_ms) == {"embed", "search", "rerank"}
    assert all(isinstance(value, int) and value >= 0 for value in trace.timings_ms.values())


def _texts_of(records: Sequence[logging.LogRecord]) -> list[str]:
    return [f"{record.getMessage()} {record.msg!r} {record.args!r}" for record in records]


async def test_no_text_in_logs_or_trace(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, caplog: pytest.LogCaptureFixture
) -> None:
    a = two_orgs.a
    secret, s_folder = await add_collection(
        conn_a, a, name="Secret", access_level="restricted", groups=("managers",)
    )
    public, p_folder = await add_collection(conn_a, a, name="Open", access_level="public")
    await add_indexed_document(
        conn_a, a, secret, s_folder, [f"salary bands {SENTINEL}"], embedder=EMBEDDER
    )
    await add_indexed_document(
        conn_a, a, public, p_folder, [f"office hours {SENTINEL}"], embedder=EMBEDDER
    )
    scope = KnowledgeScope(a.workspace_id, (secret, public))
    caplog.set_level(logging.DEBUG)
    results = [
        await run(conn_a, a, f"salary bands {SENTINEL}?", principal, scope)
        for principal in (MANAGER, MEMBER)
    ]
    assert SENTINEL in results[0].passages[0].text  # the text was loaded, so the check means it
    assert any(r.getMessage().startswith("retrieval_done ") for r in caplog.records)
    assert [line for line in _texts_of(caplog.records) if SENTINEL in line] == []
    for result in results:
        assert SENTINEL not in repr(result.trace)


async def test_fake_group_settings_have_no_effect(
    conn_a: AsyncConnection, two_orgs: TwoOrgs, corpus: PermissionCorpus
) -> None:
    for setting in ("app.user_groups", "app.groups"):
        await conn_a.execute(text("SELECT set_config(:name, 'managers', true)"), {"name": setting})
    a = two_orgs.a
    principal = session_principal(TenantContext(org_id=a.org_id, user_id=a.user_id))
    result = await run(conn_a, a, MH_QUESTION, principal, corpus.scope, 10)
    mh = corpus.collections["managers"]
    assert mh not in collections_of(result)
    assert Skipped("collection", mh, "no_access") in result.trace.skipped
    assert result.trace.group_count == 0


@pytest.mark.isolation
async def test_org_b_cannot_retrieve_org_a_scope(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        corpus = await build_permission_corpus(conn, a, EMBEDDER)
    ids = tuple(corpus.collections.values())
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        for workspace in (b.workspace_id, a.workspace_id):
            scope = KnowledgeScope(workspace, ids, (a.folder_id,))
            result = await run(conn, b, MH_QUESTION, MANAGER, scope, 10)
            assert result.passages == ()
            assert result.trace.searched == ()
            assert len(result.trace.skipped) == len(ids) + 1
            assert {item.reason for item in result.trace.skipped} == {"not_found"}


async def test_missing_chunk_is_dropped(
    conn_a: AsyncConnection,
    two_orgs: TwoOrgs,
    corpus: PermissionCorpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = "What are the office opening hours?"
    before = await run(conn_a, two_orgs.a, question, MEMBER, corpus.scope)
    gone = before.passages[0].chunk_id
    real = load_passages

    async def without_one(*args: Any, **kwargs: Any) -> Any:
        rows = await real(*args, **kwargs)
        rows.pop(gone, None)
        return rows

    monkeypatch.setattr(service, "load_passages", without_one)
    after = await run(conn_a, two_orgs.a, question, MEMBER, corpus.scope)
    assert gone not in [passage.chunk_id for passage in after.passages]
    assert gone not in [hit.chunk_id for hit in after.trace.candidates]
    expected = [hit.chunk_id for hit in before.trace.candidates if hit.chunk_id != gone][:4]
    assert [passage.chunk_id for passage in after.passages] == expected
