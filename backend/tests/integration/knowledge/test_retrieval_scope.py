"""EA-36: a knowledge scope resolves to the collections a principal may read, with a reason for
each skipped id; passages load only from ready documents of readable collections."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.knowledge.retrieval.passage_rows import load_passages
from ei_ai.knowledge.retrieval.principal import (
    AnonymousPrincipal,
    AuthenticatedPrincipal,
    RetrievalPrincipal,
)
from ei_ai.knowledge.retrieval.scope import (
    KnowledgeScope,
    ResolvedScope,
    Skipped,
    resolve_scope,
)
from ei_ai.knowledge.retrieval.scope_rows import workspace_collection_ids, workspace_exists
from support.fake_embedder import FakeEmbedder
from support.retrieval_corpus import (
    add_collection,
    add_folder,
    add_indexed_document,
    add_workspace,
)
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

MEMBER = AuthenticatedPrincipal(user_id=uuid.uuid4())
ANON = AnonymousPrincipal()


@pytest.fixture
async def conn_a(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> AsyncIterator[AsyncConnection]:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        yield conn


async def _resolve(
    conn: AsyncConnection,
    org: OrgRows,
    scope: KnowledgeScope,
    principal: RetrievalPrincipal = MEMBER,
) -> ResolvedScope:
    return await resolve_scope(conn, org.org_id, scope, principal)


async def test_readable_collections_are_searched(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    public, _ = await add_collection(conn_a, a, name="Pub", access_level="public")
    auth, _ = await add_collection(conn_a, a, name="Auth", access_level="authenticated")
    scope = KnowledgeScope(a.workspace_id, collection_ids=(auth, public, auth))
    resolved = await _resolve(conn_a, a, scope)
    assert resolved.searched_collection_ids == (auth, public)
    assert resolved.readable_collection_ids == (auth, public)
    assert resolved.folder_ids == ()
    assert resolved.skipped == ()
    anonymous = await _resolve(conn_a, a, scope, ANON)
    assert anonymous.searched_collection_ids == (public,)
    assert anonymous.skipped == (Skipped("collection", auth, "no_access"),)


async def test_unreadable_collection_is_skipped_no_access(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    open_id, _ = await add_collection(conn_a, a, name="Open", access_level="public")
    secret, _ = await add_collection(
        conn_a, a, name="Secret", access_level="restricted", groups=["managers"]
    )
    scope = KnowledgeScope(a.workspace_id, collection_ids=(secret, open_id))
    resolved = await _resolve(conn_a, a, scope)
    assert resolved.searched_collection_ids == (open_id,)
    assert resolved.readable_collection_ids == (open_id,)
    assert resolved.skipped == (Skipped("collection", secret, "no_access"),)
    manager = AuthenticatedPrincipal(user_id=None, groups=("managers",), simulated=True)
    assert (await _resolve(conn_a, a, scope, manager)).searched_collection_ids == (secret, open_id)


async def test_folder_scope_includes_sub_folders(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    coll, f1 = await add_collection(conn_a, a, name="Tree", access_level="authenticated")
    f1a = await add_folder(conn_a, a, coll, parent_id=f1, name="a")
    f1ab = await add_folder(conn_a, a, coll, parent_id=f1a, name="b")
    other = await add_folder(conn_a, a, coll, name="other")
    resolved = await _resolve(conn_a, a, KnowledgeScope(a.workspace_id, folder_ids=(f1,)))
    assert resolved.searched_collection_ids == ()
    assert set(resolved.folder_ids) == {f1, f1a, f1ab}
    assert other not in resolved.folder_ids
    assert resolved.readable_collection_ids == (coll,)
    assert resolved.skipped == ()
    # a sub-folder listed together with its parent appears once
    both = await _resolve(conn_a, a, KnowledgeScope(a.workspace_id, folder_ids=(f1a, f1)))
    assert len(both.folder_ids) == 3
    assert set(both.folder_ids) == {f1, f1a, f1ab}


async def test_folder_in_unreadable_collection_is_skipped_as_folder_only(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    secret, folder = await add_collection(
        conn_a, a, name="Secret", access_level="restricted", groups=["managers"]
    )
    resolved = await _resolve(conn_a, a, KnowledgeScope(a.workspace_id, folder_ids=(folder,)))
    assert resolved.skipped == (Skipped("folder", folder, "no_access"),)
    assert resolved.folder_ids == ()
    assert resolved.searched_collection_ids == ()
    assert resolved.readable_collection_ids == ()
    assert secret not in {item.id for item in resolved.skipped}


async def test_other_workspace_ids_are_not_found(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    ws2 = await add_workspace(conn_a, a, "Second")
    foreign, foreign_folder = await add_collection(
        conn_a, a, name="Elsewhere", access_level="public", workspace_id=ws2
    )
    unknown = uuid.uuid4()
    scope = KnowledgeScope(
        a.workspace_id,
        collection_ids=(foreign, unknown),
        folder_ids=(foreign_folder, unknown),
    )
    resolved = await _resolve(conn_a, a, scope)
    assert resolved.skipped == (
        Skipped("collection", foreign, "not_found"),
        Skipped("collection", unknown, "not_found"),
        Skipped("folder", foreign_folder, "not_found"),
        Skipped("folder", unknown, "not_found"),
    )
    assert resolved.readable_collection_ids == ()
    assert resolved.folder_ids == ()


@pytest.mark.isolation
async def test_other_org_ids_are_not_found(conn_a: AsyncConnection, two_orgs: TwoOrgs) -> None:
    a, b = two_orgs.a, two_orgs.b
    scope = KnowledgeScope(
        a.workspace_id, collection_ids=(b.collection_id,), folder_ids=(b.folder_id,)
    )
    resolved = await _resolve(conn_a, a, scope)
    assert resolved.skipped == (
        Skipped("collection", b.collection_id, "not_found"),
        Skipped("folder", b.folder_id, "not_found"),
    )
    assert resolved.searched_collection_ids == resolved.readable_collection_ids == ()
    assert resolved.folder_ids == ()


async def test_empty_scope_resolves_to_nothing(conn_a: AsyncConnection, two_orgs: TwoOrgs) -> None:
    resolved = await _resolve(conn_a, two_orgs.a, KnowledgeScope(two_orgs.a.workspace_id))
    assert resolved == ResolvedScope((), (), (), ())


async def test_load_passages_returns_text_and_location(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    coll, folder = await add_collection(conn_a, a, name="Docs", access_level="public")
    document = await add_indexed_document(
        conn_a, a, coll, folder, ["alpha beta", "gamma delta"], embedder=FakeEmbedder()
    )
    rows = (
        await conn_a.execute(
            text("SELECT id, ordinal FROM document_chunks WHERE org_id = :o AND document_id = :d"),
            {"o": a.org_id, "d": document},
        )
    ).all()
    ids = [row.id for row in sorted(rows, key=lambda row: row.ordinal)]
    passages = await load_passages(conn_a, a.org_id, [*ids, uuid.uuid4()], [coll])
    assert set(passages) == set(ids)
    second = passages[ids[1]]
    assert second.text == "gamma delta"
    assert second.document_id == document
    assert second.collection_id == coll
    assert second.folder_id == folder
    assert second.ordinal == 1
    assert second.page == 2
    assert second.heading_path == ("Part", "Section 1")
    assert second.document_name.startswith("doc-")


async def test_load_passages_drops_unready_and_unreadable(
    conn_a: AsyncConnection, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    embedder = FakeEmbedder()
    readable, f_read = await add_collection(conn_a, a, name="Read", access_level="public")
    hidden, f_hidden = await add_collection(conn_a, a, name="Hidden", access_level="public")
    ready = await add_indexed_document(conn_a, a, readable, f_read, ["one"], embedder=embedder)
    queued = await add_indexed_document(conn_a, a, readable, f_read, ["two"], embedder=embedder)
    other = await add_indexed_document(conn_a, a, hidden, f_hidden, ["three"], embedder=embedder)
    await conn_a.execute(
        text("UPDATE documents SET status = 'queued' WHERE org_id = :o AND id = :d"),
        {"o": a.org_id, "d": queued},
    )
    rows = (
        await conn_a.execute(
            text(
                "SELECT id, document_id FROM document_chunks WHERE org_id = :o"
                " AND document_id = ANY(:docs)"
            ),
            {"o": a.org_id, "docs": [ready, queued, other]},
        )
    ).all()
    by_doc = {row.document_id: row.id for row in rows}
    passages = await load_passages(conn_a, a.org_id, list(by_doc.values()), [readable])
    assert set(passages) == {by_doc[ready]}
    assert await load_passages(conn_a, a.org_id, list(by_doc.values()), []) == {}


@pytest.mark.isolation
async def test_load_passages_is_org_scoped(conn_a: AsyncConnection, two_orgs: TwoOrgs) -> None:
    a, b = two_orgs.a, two_orgs.b
    assert await load_passages(conn_a, a.org_id, [b.chunk_id], [b.collection_id]) == {}


async def test_workspace_helpers(conn_a: AsyncConnection, two_orgs: TwoOrgs) -> None:
    a, b = two_orgs.a, two_orgs.b
    assert await workspace_exists(conn_a, a.org_id, a.workspace_id)
    assert not await workspace_exists(conn_a, a.org_id, b.workspace_id)
    assert not await workspace_exists(conn_a, a.org_id, uuid.uuid4())
    zed, _ = await add_collection(conn_a, a, name="zed", access_level="public")
    alpha, _ = await add_collection(conn_a, a, name="Alpha", access_level="public")
    ws2 = await add_workspace(conn_a, a, "Second")
    elsewhere, _ = await add_collection(
        conn_a, a, name="Aaa", access_level="public", workspace_id=ws2
    )
    ids = await workspace_collection_ids(conn_a, a.org_id, a.workspace_id)
    assert ids == (alpha, a.collection_id, zed)
    assert elsewhere not in ids
    assert b.collection_id not in ids
