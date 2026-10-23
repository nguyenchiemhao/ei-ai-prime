"""Vector access metadata follows the collection (EA-35 R10, R23): an access change rewrites the
``access_level``/``groups`` of every vector of the collection in the same transaction. A running
index job embeds without row locks, so the access change does not wait for it; the job then
writes under the collection lock with the values current at that moment, so the stale copy never
survives. A document that stops being ready while it is embedded gets no vectors."""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import tenant_transaction
from ei_ai.jobs.envelope import envelope_for
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge import service
from ei_ai.knowledge.indexing.job import INDEX_DOCUMENT
from ei_ai.knowledge.ingestion.job import INGEST_DOCUMENT
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runner import IngestionRunner
from ei_ai.knowledge.ingestion.runtime import IngestionRuntime, use_runtime
from ei_ai.storage.files import OrgFileStore
from ei_ai.tenancy.context import TenantContext
from ei_ai.vectors.partitions import create_vector_partition
from support.fake_embedder import FakeEmbedder
from support.rbac.orgs import RoleOrg

from .conftest import MakeOrg, file_store, run_as

pytestmark = pytest.mark.integration

SENTENCE = "Nhân viên được nghỉ phép năm theo quy định của công ty và phải gửi đơn trước. "
BODY = "\n\n".join(SENTENCE * 25 for _ in range(3)) + "\n"


@pytest.fixture
def storage(tmp_path: Path) -> OrgFileStore:
    return file_store(tmp_path)


@pytest.fixture
async def pooled_engine() -> AsyncIterator[AsyncEngine]:
    """Several connections, so the index job and another transaction really overlap (the
    ``app_engine`` pool has one connection, where the second caller waits for the pool)."""
    engine = create_async_engine(
        to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=4, max_overflow=0
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def _org(make_org: MakeOrg) -> RoleOrg:
    """A role Organization with its vector partition (dropped when ``make_org`` purges it)."""
    org: RoleOrg = await make_org()
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"], autocommit=True) as migrator:
        create_vector_partition(migrator, org.org_id)
    return org


def _tenant(org: RoleOrg) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user("ke"))


async def _collection(engine: AsyncEngine, org: RoleOrg) -> tuple[uuid.UUID, uuid.UUID]:
    """An authenticated collection of workspace x with one folder: ``(collection, folder)``."""
    collection_id, folder_id = uuid.uuid4(), uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        await conn.execute(
            text(
                "INSERT INTO collections (id, org_id, workspace_id, name, access_level, groups)"
                " VALUES (:id, :org, :ws, :name, 'authenticated', '{}')"
            ),
            {
                "id": collection_id,
                "org": org.org_id,
                "ws": org.workspace("x"),
                "name": f"sync-{collection_id.hex[:8]}",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO folders (id, org_id, collection_id, name, depth)"
                " VALUES (:id, :org, :collection, 'sync', 1)"
            ),
            {"id": folder_id, "org": org.org_id, "collection": collection_id},
        )
    return collection_id, folder_id


async def _ready_document(
    engine: AsyncEngine,
    storage: OrgFileStore,
    org: RoleOrg,
    place: tuple[uuid.UUID, uuid.UUID],
    embedder: FakeEmbedder | None,
) -> uuid.UUID:
    """A TXT document in ``place`` run through ingestion; indexed when ``embedder`` is given."""
    document_id = uuid.uuid4()
    data = BODY.encode("utf-8")
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        file_id = await storage.put(conn, _tenant(org), data)
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
                " size_bytes, status, uploaded_by, file_id)"
                " VALUES (:id, :org, :collection, :folder, 'sync.txt', 'txt', :size, 'queued',"
                " :user, :file)"
            ),
            {
                "id": document_id,
                "org": org.org_id,
                "collection": place[0],
                "folder": place[1],
                "size": len(data),
                "user": org.user("ke"),
                "file": file_id,
            },
        )
    runner = IngestionRunner(
        lambda: engine, lambda: storage, ProgressBoard(), embedder=lambda: embedder
    )
    runner.submit(envelope_for(_tenant(org), INGEST_DOCUMENT, {"document_id": str(document_id)}))
    await runner.drain()
    return document_id


async def _access_of_vectors(
    engine: AsyncEngine, org: RoleOrg, collection_id: uuid.UUID
) -> set[tuple[str, tuple[str, ...]]]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT access_level, groups FROM chunk_embeddings"
                " WHERE org_id = :org AND collection_id = :collection"
            ),
            {"org": org.org_id, "collection": collection_id},
        )
        return {(row.access_level, tuple(row.groups)) for row in result}


async def _vector_count(engine: AsyncEngine, org: RoleOrg, collection_id: uuid.UUID) -> int:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT count(*) FROM chunk_embeddings"
                " WHERE org_id = :org AND collection_id = :collection"
            ),
            {"org": org.org_id, "collection": collection_id},
        )
        return int(result.scalar_one())


async def _change_access(
    engine: AsyncEngine,
    org: RoleOrg,
    collection_id: uuid.UUID,
    level: str,
    groups: Sequence[str],
) -> None:
    async def work(conn: Any, tenant: Any, access: Any) -> None:
        await service.change_access(
            conn, tenant, access, collection_id, access_level=level, groups=groups
        )

    await run_as(engine, org, "ws_admin", work)


async def test_access_change_updates_vector_metadata_in_the_same_transaction(
    app_engine: AsyncEngine, make_org: MakeOrg, storage: OrgFileStore
) -> None:
    org = await _org(make_org)
    place = await _collection(app_engine, org)
    other = await _collection(app_engine, org)
    await _ready_document(app_engine, storage, org, place, FakeEmbedder())
    await _ready_document(app_engine, storage, org, other, FakeEmbedder())
    assert await _vector_count(app_engine, org, place[0]) >= 2

    await _change_access(app_engine, org, place[0], "restricted", ["hr-team"])

    assert await _access_of_vectors(app_engine, org, place[0]) == {("restricted", ("hr-team",))}
    assert await _access_of_vectors(app_engine, org, other[0]) == {("authenticated", ())}

    await _change_access(app_engine, org, place[0], "public", [])

    assert await _access_of_vectors(app_engine, org, place[0]) == {("public", ())}
    assert await _access_of_vectors(app_engine, org, other[0]) == {("authenticated", ())}


@asynccontextmanager
async def _paused_index_job(
    engine: AsyncEngine, storage: OrgFileStore, org: RoleOrg, document_id: uuid.UUID
) -> AsyncIterator["asyncio.Task[None]"]:
    """Runs the index job of ``document_id`` and yields it while it waits inside the embedder.

    On exit the embedder is released and the job awaited, so its error (if any) fails the test.
    """
    gate = asyncio.Event()
    embedder = FakeEmbedder(gate=gate)
    index = envelope_for(_tenant(org), INDEX_DOCUMENT, {"document_id": str(document_id)})
    with use_runtime(IngestionRuntime(storage, ProgressBoard(), embedder)):
        job = asyncio.create_task(run_tenant_job(engine, index))
        try:
            for _ in range(200):
                if embedder.calls:
                    break
                await asyncio.sleep(0.05)
            assert embedder.calls, "the index job never reached the embedder"
            yield job
        finally:
            gate.set()
            await asyncio.wait_for(job, timeout=30)


async def _execute(engine: AsyncEngine, org: RoleOrg, statement: str, **params: Any) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        await conn.execute(text(statement), {"org": org.org_id, **params})


async def test_access_change_does_not_wait_for_a_running_index_job_and_wins(
    app_engine: AsyncEngine, make_org: MakeOrg, storage: OrgFileStore, pooled_engine: AsyncEngine
) -> None:
    org = await _org(make_org)
    place = await _collection(app_engine, org)
    document_id = await _ready_document(app_engine, storage, org, place, None)

    async with _paused_index_job(pooled_engine, storage, org, document_id) as job:
        change = _change_access(pooled_engine, org, place[0], "restricted", ["hr-team"])
        await asyncio.wait_for(change, timeout=2)
        assert not job.done(), "the index job finished before the embedder was released"

    assert await _vector_count(app_engine, org, place[0]) >= 2
    assert await _access_of_vectors(app_engine, org, place[0]) == {("restricted", ("hr-team",))}


async def test_document_deleted_while_embedding_gets_no_vectors(
    app_engine: AsyncEngine,
    make_org: MakeOrg,
    storage: OrgFileStore,
    pooled_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    org = await _org(make_org)
    place = await _collection(app_engine, org)
    document_id = await _ready_document(app_engine, storage, org, place, None)
    delete = "DELETE FROM documents WHERE org_id = :org AND id = :id"

    caplog.set_level(logging.INFO, logger="ei_ai.knowledge.indexing")

    async with _paused_index_job(pooled_engine, storage, org, document_id):
        await asyncio.wait_for(_execute(pooled_engine, org, delete, id=document_id), timeout=2)

    assert await _vector_count(app_engine, org, place[0]) == 0
    messages = [r.getMessage() for r in caplog.records if r.name == "ei_ai.knowledge.indexing"]
    assert messages == [f"document_index_skipped document_id={document_id} org_id={org.org_id}"]


async def test_document_whose_chunks_change_while_embedding_gets_no_vectors(
    app_engine: AsyncEngine, make_org: MakeOrg, storage: OrgFileStore, pooled_engine: AsyncEngine
) -> None:
    org = await _org(make_org)
    place = await _collection(app_engine, org)
    document_id = await _ready_document(app_engine, storage, org, place, None)
    drop_last_chunk = (
        "DELETE FROM document_chunks WHERE org_id = :org AND document_id = :id"
        " AND ordinal = (SELECT max(ordinal) FROM document_chunks"
        " WHERE org_id = :org AND document_id = :id)"
    )

    async with _paused_index_job(pooled_engine, storage, org, document_id):
        await asyncio.wait_for(
            _execute(pooled_engine, org, drop_last_chunk, id=document_id), timeout=2
        )

    assert await _vector_count(app_engine, org, place[0]) == 0


async def test_access_change_in_org_b_does_not_touch_org_a_vectors(
    app_engine: AsyncEngine, make_org: MakeOrg, storage: OrgFileStore
) -> None:
    a, b = await _org(make_org), await _org(make_org)
    place_a = await _collection(app_engine, a)
    place_b = await _collection(app_engine, b)
    await _ready_document(app_engine, storage, a, place_a, FakeEmbedder())
    await _ready_document(app_engine, storage, b, place_b, FakeEmbedder())

    await _change_access(app_engine, b, place_b[0], "restricted", ["hr-team"])

    assert await _access_of_vectors(app_engine, b, place_b[0]) == {("restricted", ("hr-team",))}
    assert await _access_of_vectors(app_engine, a, place_a[0]) == {("authenticated", ())}
