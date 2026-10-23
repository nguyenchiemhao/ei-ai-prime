"""The document ingestion job: real PostgreSQL, encrypted files in ``tmp_path`` (EA-33)."""

import logging
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.crypto.lifecycle import destroy_org_key
from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import TenantExecutor, tenant_transaction
from ei_ai.jobs.envelope import envelope_for
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge.ingestion import job as ingestion_job
from ei_ai.knowledge.ingestion import result_rows
from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.job import INGEST_DOCUMENT
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runtime import IngestionRuntime, use_runtime
from ei_ai.storage.files import OrgFileStore
from ei_ai.tenancy.context import TenantContext
from support.crypto import TEST_MASTER_KEY
from support.documents import make_blank_pdf, make_text_pdf
from support.tenants import OrgRows, TwoOrgs

from .conftest import document_file_id, document_row, queue_document

pytestmark = pytest.mark.integration

PAGE_TEXT = "This page has a real text layer with enough characters to count. " * 4


class RecordingStorage(OrgFileStore):
    """The encrypted file store, remembering which (Organization, file id) pairs were read."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, OrgCipher(TEST_MASTER_KEY))
        self.reads: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def get(self, session: TenantExecutor, tenant: Any, file_id: uuid.UUID) -> bytes:
        self.reads.append((tenant.org_id, file_id))
        return await super().get(session, tenant, file_id)


@pytest.fixture
def storage(tmp_path: Path) -> RecordingStorage:
    return RecordingStorage(tmp_path)


@pytest.fixture
def board() -> ProgressBoard:
    return ProgressBoard()


@pytest.fixture
def runtime(storage: RecordingStorage, board: ProgressBoard) -> Iterator[IngestionRuntime]:
    with use_runtime(IngestionRuntime(storage, board)) as current:
        yield current


def _tenant(org: OrgRows) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user_id)


async def run_ingest(engine: AsyncEngine, org: OrgRows, document_id: uuid.UUID) -> None:
    envelope = envelope_for(_tenant(org), INGEST_DOCUMENT, {"document_id": str(document_id)})
    await run_tenant_job(engine, envelope)


async def test_text_pdf_becomes_ready_with_chunks(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: RecordingStorage, runtime: Any
) -> None:
    a = two_orgs.a
    pdf = make_text_pdf([PAGE_TEXT, PAGE_TEXT, PAGE_TEXT])
    document_id = await queue_document(app_engine, storage, a, "pdf", pdf)

    await run_ingest(app_engine, a, document_id)

    row = await document_row(app_engine, a, document_id)
    assert (row.status, row.reason, row.page_count) == ("ready", None, 3)
    assert row.chunks == row.chunk_count >= 3
    assert row.extracted_text.startswith("This page has a real text layer")
    assert row.processed_at is not None
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        chunks = (
            await conn.execute(
                text(
                    "SELECT ordinal, text, page, heading_path, char_start, char_end"
                    " FROM document_chunks WHERE org_id = :org AND document_id = :id"
                    " ORDER BY ordinal"
                ),
                {"org": a.org_id, "id": document_id},
            )
        ).all()
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert [chunk.page for chunk in chunks] == [1, 2, 3]
    assert all(chunk.heading_path == [] for chunk in chunks)
    assert all(
        chunk.text == row.extracted_text[chunk.char_start : chunk.char_end] for chunk in chunks
    )


async def test_scanned_pdf_not_supported_no_chunks(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: RecordingStorage, runtime: Any
) -> None:
    a = two_orgs.a
    document_id = await queue_document(app_engine, storage, a, "pdf", make_blank_pdf(2))

    await run_ingest(app_engine, a, document_id)

    row = await document_row(app_engine, a, document_id)
    assert (row.status, row.reason, row.chunks, row.chunk_count) == (
        "not_supported",
        "scanned_pdf",
        0,
        0,
    )
    assert row.extracted_text is None
    assert row.processed_at is not None


async def test_job_ignores_document_of_other_org(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: RecordingStorage,
    board: ProgressBoard,
    runtime: Any,
) -> None:
    a, b = two_orgs.a, two_orgs.b
    document_id = await queue_document(app_engine, storage, b, "txt", b"Text of B. " * 20)
    before = await document_row(app_engine, b, document_id)

    await run_ingest(app_engine, a, document_id)

    assert await document_row(app_engine, b, document_id) == before
    assert storage.reads == []
    assert board.read(_tenant(a), document_id) is None
    assert board.read(_tenant(b), document_id) is None


async def test_job_skips_non_queued_document(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: RecordingStorage, runtime: Any
) -> None:
    a = two_orgs.a
    before = await document_row(app_engine, a, a.document_id)

    await run_ingest(app_engine, a, a.document_id)

    assert await document_row(app_engine, a, a.document_id) == before
    assert storage.reads == []


async def test_missing_file_fails_processing_error(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: RecordingStorage, runtime: Any
) -> None:
    a = two_orgs.a
    document_id = await queue_document(app_engine, None, a, "txt", b"never stored")

    await run_ingest(app_engine, a, document_id)

    row = await document_row(app_engine, a, document_id)
    assert (row.status, row.reason, row.chunks) == ("failed", "processing_error", 0)
    file_id = await document_file_id(app_engine, a.org_id, document_id)
    assert storage.reads == [(a.org_id, file_id)]


async def test_failed_job_logs_no_name_or_text(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: RecordingStorage,
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = two_orgs.a
    secret_name = f"secret-name-{uuid.uuid4().hex}"
    secret_text = f"secret-text-{uuid.uuid4().hex}"
    document_id = await queue_document(
        app_engine, storage, a, "txt", secret_text.encode(), name=secret_name
    )

    def explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError(f"cannot parse {secret_name}.txt: {secret_text}")

    monkeypatch.setattr(ingestion_job, "extract_document", explode)
    caplog.set_level(logging.DEBUG)

    await run_ingest(app_engine, a, document_id)

    row = await document_row(app_engine, a, document_id)
    assert (row.status, row.reason) == ("failed", "processing_error")
    assert secret_name not in caplog.text
    assert secret_text not in caplog.text
    failures = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert failures == [
        f"document_ingest_failed document_id={document_id} org_id={a.org_id}"
        " format=txt size_bytes=" + str(len(secret_text)) + " error=RuntimeError"
    ]


async def test_key_failure_logs_no_name_or_text(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: RecordingStorage,
    runtime: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = two_orgs.a
    secret_name = f"secret-name-{uuid.uuid4().hex}"
    secret_text = f"secret-text-{uuid.uuid4().hex}"
    document_id = await queue_document(
        app_engine, storage, a, "txt", secret_text.encode(), name=secret_name
    )
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await destroy_org_key(conn, a.org_id)
    caplog.set_level(logging.DEBUG)

    await run_ingest(app_engine, a, document_id)

    row = await document_row(app_engine, a, document_id)
    assert (row.status, row.reason) == ("failed", "processing_error")
    master_hex = TEST_MASTER_KEY.key.hex()
    assert secret_name not in caplog.text
    assert secret_text not in caplog.text
    assert master_hex not in caplog.text.lower()
    failures = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert failures == [
        f"document_ingest_failed document_id={document_id} org_id={a.org_id}"
        " format=txt size_bytes=" + str(len(secret_text)) + " error=KeyDestroyed"
    ]


async def test_successful_job_logs_no_name_or_text(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: RecordingStorage,
    runtime: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = two_orgs.a
    secret_name = f"secret-name-{uuid.uuid4().hex}"
    secret_text = f"secret-text-{uuid.uuid4().hex}"
    document_id = await queue_document(
        app_engine, storage, a, "md", f"# {secret_text}\n\nBody".encode(), name=secret_name
    )
    caplog.set_level(logging.DEBUG)

    await run_ingest(app_engine, a, document_id)

    assert (await document_row(app_engine, a, document_id)).status == "ready"
    assert secret_name not in caplog.text
    assert secret_text not in caplog.text
    assert str(document_id) in caplog.text


async def test_one_failing_document_does_not_affect_another(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, storage: RecordingStorage, runtime: Any
) -> None:
    a = two_orgs.a
    broken = await queue_document(app_engine, storage, a, "pdf", uuid.uuid4().bytes * 64)
    good = await queue_document(app_engine, storage, a, "txt", b"A good plain text file.\n")

    await run_ingest(app_engine, a, broken)
    await run_ingest(app_engine, a, good)

    broken_row = await document_row(app_engine, a, broken)
    good_row = await document_row(app_engine, a, good)
    assert (broken_row.status, broken_row.reason, broken_row.chunks) == (
        "failed",
        "corrupt_file",
        0,
    )
    assert (good_row.status, good_row.reason, good_row.page_count, good_row.chunks) == (
        "ready",
        None,
        1,
        1,
    )


async def test_failure_while_saving_rolls_back_the_chunks(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: RecordingStorage,
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = two_orgs.a
    document_id = await queue_document(app_engine, storage, a, "txt", b"Some text to chunk.\n")
    real_save_ready = result_rows.save_ready

    async def save_then_fail(conn: AsyncConnection, *args: Any) -> None:
        await real_save_ready(conn, *args)
        raise RuntimeError("database went away")

    monkeypatch.setattr(ingestion_job, "save_ready", save_then_fail)

    await run_ingest(app_engine, a, document_id)

    row = await document_row(app_engine, a, document_id)
    assert (row.status, row.reason, row.chunks, row.chunk_count) == (
        "failed",
        "processing_error",
        0,
        0,
    )
    assert row.extracted_text is None


async def test_job_reports_progress_while_running(
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    storage: RecordingStorage,
    board: ProgressBoard,
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = two_orgs.a
    document_id = await queue_document(app_engine, storage, a, "txt", b"Plain text.\n")
    seen: list[Any] = []

    def extract_and_look(*args: Any) -> Any:
        seen.append(board.read(_tenant(a), document_id))
        return extract_document(*args)

    monkeypatch.setattr(ingestion_job, "extract_document", extract_and_look)

    await run_ingest(app_engine, a, document_id)

    assert seen and seen[0] is not None and seen[0].running
    assert (await document_row(app_engine, a, document_id)).status == "ready"


async def test_job_without_runtime_on_a_queued_document_raises(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    document_id = await queue_document(app_engine, None, a, "txt", b"x")

    with pytest.raises(RuntimeError, match="ingestion runtime"):
        await run_ingest(app_engine, a, document_id)

    assert (await document_row(app_engine, a, document_id)).status == "queued"


async def test_lock_skips_a_document_locked_by_another_job(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    document_id = await queue_document(app_engine, None, a, "txt", b"x")
    second_engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]))

    try:
        async with app_engine.connect() as first, tenant_transaction(first, a.org_id):
            held = await result_rows.lock_queued_document(first, a.org_id, document_id)
            async with second_engine.connect() as second, tenant_transaction(second, a.org_id):
                skipped = await result_rows.lock_queued_document(second, a.org_id, document_id)
    finally:
        await second_engine.dispose()

    assert held is not None and held.id == document_id
    assert skipped is None
