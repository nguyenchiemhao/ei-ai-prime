"""Indexing of ready documents into the Organization's vector partition (EA-35 AC1, AC3, AC4, AC6).

Real PostgreSQL + pgvector, encrypted originals in ``tmp_path``, the deterministic
``FakeEmbedder`` instead of a model (no network).
"""

import logging
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.jobs.envelope import JobEnvelope, envelope_for
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge.indexing import index_rows
from ei_ai.knowledge.indexing import job as indexing_job
from ei_ai.knowledge.indexing.job import INDEX_DOCUMENT
from ei_ai.knowledge.ingestion.job import INGEST_DOCUMENT
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runner import IngestionRunner
from ei_ai.knowledge.ingestion.runtime import IngestionRuntime, use_runtime
from ei_ai.knowledge.rows import document_counts
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.storage.files import OrgFileStore
from ei_ai.tenancy.context import TenantContext
from support.fake_embedder import FakeEmbedder
from support.tenants import OrgRows, TwoOrgs

from .conftest import document_row, file_store

pytestmark = pytest.mark.integration

SENTINEL = "zebracorn7q4sentinel"
SENTENCE = "Nhân viên được nghỉ phép năm theo quy định của công ty và phải gửi đơn trước. "
# About three chunks (a chunk is ~400 tokens of ~4 characters).
BODY = "\n\n".join(SENTENCE * 25 for _ in range(3)) + f"\n\nMã kiểm tra {SENTINEL}.\n"


def _tenant(org: OrgRows) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user_id)


@pytest.fixture
def storage(tmp_path: Path) -> OrgFileStore:
    return file_store(tmp_path)


async def _collection(
    engine: AsyncEngine,
    org: OrgRows,
    access_level: str = "authenticated",
    groups: Sequence[str] = (),
) -> tuple[uuid.UUID, uuid.UUID]:
    """A new collection of the org's fixture workspace with one folder: ``(collection, folder)``."""
    collection_id, folder_id = uuid.uuid4(), uuid.uuid4()
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        await conn.execute(
            text(
                "INSERT INTO collections (id, org_id, workspace_id, name, access_level, groups)"
                " VALUES (:id, :org, :ws, :name, :level, :groups)"
            ),
            {
                "id": collection_id,
                "org": org.org_id,
                "ws": org.workspace_id,
                "name": f"qa-index-{collection_id.hex[:8]}",
                "level": access_level,
                "groups": list(groups),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO folders (id, org_id, collection_id, name, depth)"
                " VALUES (:id, :org, :collection, 'qa-index', 1)"
            ),
            {"id": folder_id, "org": org.org_id, "collection": collection_id},
        )
    return collection_id, folder_id


async def _queue(
    engine: AsyncEngine,
    storage: OrgFileStore,
    org: OrgRows,
    place: tuple[uuid.UUID, uuid.UUID],
    body: str = BODY,
) -> uuid.UUID:
    """A ``queued`` TXT document in ``place`` with its original stored encrypted."""
    document_id = uuid.uuid4()
    data = body.encode("utf-8")
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        file_id = await storage.put(conn, _tenant(org), data)
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, collection_id, folder_id, name, format,"
                " size_bytes, status, uploaded_by, file_id)"
                " VALUES (:id, :org, :collection, :folder, 'qa.txt', 'txt', :size, 'queued',"
                " :user, :file)"
            ),
            {
                "id": document_id,
                "org": org.org_id,
                "collection": place[0],
                "folder": place[1],
                "size": len(data),
                "user": org.user_id,
                "file": file_id,
            },
        )
    return document_id


def _ingest(org: OrgRows, document_id: uuid.UUID) -> JobEnvelope:
    return envelope_for(_tenant(org), INGEST_DOCUMENT, {"document_id": str(document_id)})


def _index(org: OrgRows, document_id: uuid.UUID) -> JobEnvelope:
    return envelope_for(_tenant(org), INDEX_DOCUMENT, {"document_id": str(document_id)})


async def _upload_and_drain(
    engine: AsyncEngine,
    storage: OrgFileStore,
    org: OrgRows,
    embedder: FakeEmbedder | None,
    place: tuple[uuid.UUID, uuid.UUID] | None = None,
) -> uuid.UUID:
    """Queues a document, submits it to a runner with ``embedder`` and waits for every job."""
    place = place or await _collection(engine, org)
    document_id = await _queue(engine, storage, org, place)
    runner = IngestionRunner(
        lambda: engine, lambda: storage, ProgressBoard(), embedder=lambda: embedder
    )
    runner.submit(_ingest(org, document_id))
    await runner.drain()
    return document_id


async def _vectors(engine: AsyncEngine, org: OrgRows, document_id: uuid.UUID) -> list[Any]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT id, chunk_id, document_id, workspace_id, collection_id, folder_id,"
                " access_level, groups, model_id, model_version, created_at"
                " FROM chunk_embeddings WHERE org_id = :org AND document_id = :document"
                " ORDER BY chunk_id"
            ),
            {"org": org.org_id, "document": document_id},
        )
        return list(result)


async def _chunk_ids(engine: AsyncEngine, org: OrgRows, document_id: uuid.UUID) -> list[Any]:
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        result = await conn.execute(
            text(
                "SELECT id FROM document_chunks WHERE org_id = :org AND document_id = :document"
                " ORDER BY id"
            ),
            {"org": org.org_id, "document": document_id},
        )
        return [row.id for row in result]


@pytest.fixture
def capture(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    caplog.set_level(logging.DEBUG)
    yield caplog


async def test_ready_document_gets_one_vector_per_chunk_and_stays_ready(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: OrgFileStore
) -> None:
    a = two_orgs.a
    embedder = FakeEmbedder()

    document_id = await _upload_and_drain(app_engine, storage, a, embedder)

    row = await document_row(app_engine, a, document_id)
    vectors = await _vectors(app_engine, a, document_id)
    assert row.status == "ready"
    assert row.chunk_count >= 2
    assert len(vectors) == row.chunk_count
    assert [v.chunk_id for v in vectors] == await _chunk_ids(app_engine, a, document_id)
    assert embedder.calls == [row.chunk_count]


async def test_collection_counts_the_indexed_document_as_ready(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: OrgFileStore
) -> None:
    a = two_orgs.a
    place = await _collection(app_engine, a)

    await _upload_and_drain(app_engine, storage, a, FakeEmbedder(), place)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        counts = await document_counts(conn, a.org_id, [place[0]])
    assert counts[place[0]].ready == 1
    assert counts[place[0]].total == 1


async def test_every_vector_carries_collection_access_level_and_groups(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: OrgFileStore
) -> None:
    a = two_orgs.a
    place = await _collection(app_engine, a, "restricted", ["hr-team"])

    document_id = await _upload_and_drain(app_engine, storage, a, FakeEmbedder(), place)

    vectors = await _vectors(app_engine, a, document_id)
    assert vectors
    for vector in vectors:
        assert (
            vector.document_id,
            vector.workspace_id,
            vector.collection_id,
            vector.folder_id,
            vector.access_level,
            vector.groups,
        ) == (document_id, a.workspace_id, place[0], place[1], "restricted", ["hr-team"])


async def test_every_vector_stores_model_id_and_version(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: OrgFileStore
) -> None:
    a = two_orgs.a

    document_id = await _upload_and_drain(app_engine, storage, a, FakeEmbedder())

    vectors = await _vectors(app_engine, a, document_id)
    assert vectors
    assert {(v.model_id, v.model_version) for v in vectors} == {("bge-m3", "2026.10")}


async def test_embedding_failure_leaves_document_ready_and_not_indexed(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: OrgFileStore,
    capture: pytest.LogCaptureFixture,
) -> None:
    a = two_orgs.a
    failing = FakeEmbedder(
        fail=ModelError(ModelErrorCode.MODEL_UNAVAILABLE, "bge-m3@2026.10", "embedding")
    )

    document_id = await _upload_and_drain(app_engine, storage, a, failing)

    assert (await document_row(app_engine, a, document_id)).status == "ready"
    assert await _vectors(app_engine, a, document_id) == []
    messages = [r.getMessage() for r in capture.records if r.name == "ei_ai.knowledge.indexing"]
    assert messages == [
        f"document_index_failed document_id={document_id} org_id={a.org_id} error=MODEL_UNAVAILABLE"
    ]


async def test_runner_without_embedder_does_not_queue_indexing(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: OrgFileStore,
    monkeypatch: pytest.MonkeyPatch,
    capture: pytest.LogCaptureFixture,
) -> None:
    a = two_orgs.a
    reads: list[uuid.UUID] = []
    original = index_rows.ready_chunks

    async def recording_read(conn: Any, org_id: uuid.UUID, document_id: uuid.UUID) -> Any:
        reads.append(document_id)
        return await original(conn, org_id, document_id)

    monkeypatch.setattr(indexing_job, "ready_chunks", recording_read)
    document_id = await _queue(app_engine, storage, a, await _collection(app_engine, a))
    runner = IngestionRunner(lambda: app_engine, lambda: storage, ProgressBoard())

    runner.submit(_ingest(a, document_id))
    await runner.drain()

    assert (await document_row(app_engine, a, document_id)).status == "ready"
    assert reads == []
    assert await _vectors(app_engine, a, document_id) == []
    assert not [r for r in capture.records if r.name == "ei_ai.knowledge.indexing"]


async def test_index_document_twice_keeps_one_vector_per_chunk(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: OrgFileStore
) -> None:
    a = two_orgs.a
    embedder = FakeEmbedder()
    document_id = await _upload_and_drain(app_engine, storage, a, embedder)
    first = await _vectors(app_engine, a, document_id)

    with use_runtime(IngestionRuntime(storage, ProgressBoard(), embedder)):
        await run_tenant_job(app_engine, _index(a, document_id))

    second = await _vectors(app_engine, a, document_id)
    chunks = await _chunk_ids(app_engine, a, document_id)
    assert [v.chunk_id for v in second] == chunks
    assert {v.id for v in second}.isdisjoint({v.id for v in first})
    assert len(embedder.calls) == 2


async def test_index_job_of_org_b_ignores_org_a_document(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: OrgFileStore
) -> None:
    a, b = two_orgs.a, two_orgs.b
    document_id = await _upload_and_drain(app_engine, storage, a, FakeEmbedder())
    before = await _vectors(app_engine, a, document_id)
    embedder = FakeEmbedder()

    with use_runtime(IngestionRuntime(storage, ProgressBoard(), embedder)):
        await run_tenant_job(app_engine, _index(b, document_id))

    assert embedder.calls == []
    assert await _vectors(app_engine, a, document_id) == before
    assert await _vectors(app_engine, b, document_id) == []


async def test_index_job_logs_ids_and_codes_only(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: OrgFileStore,
    capture: pytest.LogCaptureFixture,
) -> None:
    a = two_orgs.a

    document_id = await _upload_and_drain(app_engine, storage, a, FakeEmbedder())

    row = await document_row(app_engine, a, document_id)
    messages = [r.getMessage() for r in capture.records if r.name == "ei_ai.knowledge.indexing"]
    assert messages == [
        f"document_indexed document_id={document_id} org_id={a.org_id}"
        f" vectors={row.chunk_count} model=bge-m3@2026.10"
    ]
    assert SENTINEL in row.extracted_text
    assert all(SENTINEL not in record.getMessage() for record in capture.records)
    assert SENTINEL not in capture.text
